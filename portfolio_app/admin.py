# /opt/easyportfolio_django_app/portfolio_app/admin.py

from django.contrib import admin
from django.utils.html import format_html_join, format_html # Für HTML-Formatierung im Admin
from django.urls import reverse # Um Links zu Admin-Seiten zu erstellen
from django.utils.safestring import mark_safe # Um HTML als sicher zu markieren

from .models import Security, HistoricalPrice, Dividend, Split, Portfolio, TargetWeight, FxRate


@admin.register(Security)
class SecurityAdmin(admin.ModelAdmin):
    list_display = ('security_name', 'ticker_symbol', 'isin', 'security_type', 'exchange', 'currency', 'benchmark', 'expert', 'last_api_update')
    list_filter = ('security_type', 'exchange', 'currency', 'benchmark', 'expert')
    search_fields = ('security_name', 'ticker_symbol', 'isin')
    ordering = ('security_name',)
    list_editable = ('exchange', 'benchmark', 'expert',)

@admin.register(Dividend)
class DividendAdmin(admin.ModelAdmin):
    list_display = ('security', 'ex_dividend_date', 'amount_per_share', 'payment_date', 'dividend_currency', 'period', 'declaration_date', 'record_date')
    list_filter = ('security__security_name', 'ex_dividend_date', 'dividend_currency', 'period') # Filter nach security_name
    search_fields = ('security__ticker_symbol', 'security__security_name')
    date_hierarchy = 'ex_dividend_date'
    list_per_page = 50
    autocomplete_fields = ['security'] # Autocomplete für Wertpapierauswahl

@admin.register(Split)
class SplitAdmin(admin.ModelAdmin):
    list_display = ('security', 'split_date', 'split_ratio_str')
    list_filter = ('security__security_name', 'split_date') # Filter nach security_name
    search_fields = ('security__ticker_symbol', 'security__security_name')
    date_hierarchy = 'split_date'
    list_per_page = 50
    autocomplete_fields = ['security']

@admin.register(HistoricalPrice)
class HistoricalPriceAdmin(admin.ModelAdmin):
    list_display = ('security', 'price_date', 'adj_close_price', 'volume', 'open_price', 'high_price', 'low_price', 'close_price')
    list_filter = ('price_date', 'security__security_type', 'security__security_name') # Filter nach security_name
    search_fields = ('security__security_name', 'security__ticker_symbol', 'price_date')
    ordering = ('security', '-price_date')
    date_hierarchy = 'price_date'
    list_per_page = 50
    autocomplete_fields = ['security']

# --- NEU: Inline-Admin für TargetWeight ---
class TargetWeightInline(admin.TabularInline): # oder admin.StackedInline für andere Optik
    model = TargetWeight
    fk_name = 'portfolio' # Explizit den Fremdschlüssel zum Portfolio-Modell angeben
    fields = ('security', 'target_weight')
    autocomplete_fields = ['security'] # Macht die Auswahl der Wertpapiere einfacher
    extra = 1  # Anzahl der leeren Formulare, die standardmäßig angezeigt werden
    verbose_name = "Wertpapier im Portfolio"
    verbose_name_plural = "Zielgewichtungen der Wertpapiere im Portfolio"
    # Optional: Mindestanzahl an Inlines
    # min_num = 1 
    # Optional: Sortierbarkeit (wenn das TargetWeight-Modell eine Reihenfolge hätte)
    # sortable_field_name = "reihenfolge_im_portfolio" 

@admin.register(Portfolio)
class PortfolioAdmin(admin.ModelAdmin):
    list_display = ('portfolio_name', 'user_display', 'expert', 'display_top_holdings', 'creation_date', 'last_modified')
    list_filter = ('expert', 'user', 'creation_date', 'last_modified')
    search_fields = ('portfolio_name', 'description', 'user__username')
    readonly_fields = ('creation_date', 'last_modified', 'display_all_holdings_nicely') # Für eine schöne Detailansicht
    list_editable = ('expert',)
    
    # Füge das Inline-Admin für TargetWeight hinzu
    inlines = [TargetWeightInline]

    fieldsets = (
        (None, {
            'fields': ('portfolio_name', 'user', 'description', 'expert')
        }),
        ('Holdings (Detailansicht)', { # Ein eigener Abschnitt für die schöne Anzeige
            'classes': ('collapse',), # Optional einklappbar machen
            'fields': ('display_all_holdings_nicely',),
        }),
        ('Zeitstempel', {
            'fields': ('creation_date', 'last_modified'),
            'classes': ('collapse',) 
        }),
    )

    def user_display(self, obj):
        return obj.user.username if obj.user else "-"
    user_display.short_description = "Benutzer"
    user_display.admin_order_field = 'user__username'


    def display_top_holdings(self, obj):
        # Zeigt die Top N Holdings (z.B. Top 3) in der Liste an
        weights = obj.target_weights.select_related('security').order_by('-target_weight')[:3]
        if not weights:
            return "Leer"
        
        holding_strings = []
        for w in weights:
            # Link zum Security-Admin-Objekt erstellen
            security_admin_url = reverse('admin:portfolio_app_security_change', args=[w.security.pk])
            # Zielgewichtung: Das Model speichert 50.0000 für 50%. Im Admin wollen wir es als % sehen.
            formatted_weight = f"{w.target_weight:.2f}".rstrip('0').rstrip('.') # Entfernt unnötige Nullen
            
            holding_strings.append(format_html(
                '<a href="{}">{}</a> ({}%)', 
                security_admin_url, 
                w.security.security_name,
                formatted_weight 
            ))
        
        summary = mark_safe(", ".join(holding_strings))
        if obj.target_weights.count() > 3:
            summary = mark_safe(summary + ", ...")
        return summary
    display_top_holdings.short_description = "Top Holdings (max. 3)"

    def display_all_holdings_nicely(self, obj):
        # Für die Detailansicht des Portfolios: Alle Holdings schön formatiert
        weights = obj.target_weights.select_related('security').order_by('-target_weight')
        if not weights:
            return "Keine Zielgewichtungen für dieses Portfolio definiert."
        
        # Erstellt eine HTML-Liste
        list_items = format_html_join(
            '\n', # Trennzeichen zwischen den <li> Elementen
            '<li style="margin-bottom: 4px;"><a href="{}">{}</a>: <strong>{:.2f}%</strong></li>', # Format für jedes Element
            (
                (
                    reverse('admin:portfolio_app_security_change', args=[w.security.pk]), 
                    w.security.security_name, 
                    w.target_weight # target_weight wird als X.YYYY gespeichert, was X.YYYY% entspricht
                ) for w in weights
            )
        )
        return mark_safe(f'<ul style="list-style-type: disc; padding-left: 20px;">{list_items}</ul>')
    display_all_holdings_nicely.short_description = "Alle Zielgewichtungen im Portfolio"


@admin.register(TargetWeight)
class TargetWeightAdmin(admin.ModelAdmin):
    list_display = ('portfolio', 'security', 'target_weight_display')
    list_filter = ('portfolio__portfolio_name', 'security__security_name') # Filter nach Namen
    search_fields = ('portfolio__portfolio_name', 'security__security_name', 'security__ticker_symbol')
    list_per_page = 50
    autocomplete_fields = ['portfolio', 'security']

    def target_weight_display(self, obj):
        # Zeigt die Gewichtung als Prozentwert an
        return f"{obj.target_weight:.2f}%" # Zwei Nachkommastellen für die Anzeige
    target_weight_display.short_description = "Zielgewichtung (%)"
    target_weight_display.admin_order_field = 'target_weight'


class FxRateAdmin(admin.ModelAdmin):
    list_display = ('rate_date', 'base_currency', 'quote_currency', 'exchange_rate', 'source')
    list_filter = ('base_currency', 'quote_currency', 'source', 'rate_date')
    search_fields = ('base_currency', 'quote_currency', 'rate_date')
    ordering = ('-rate_date', 'base_currency', 'quote_currency')
    list_per_page = 25 # Wie viele Einträge pro Seite angezeigt werden

    def created_at_local(self, obj):
        # Konvertiert created_at in die lokale Zeitzone (aus settings.TIME_ZONE)
        # für eine benutzerfreundlichere Anzeige im Admin.
        # Du hattest 'created_at' in deinem FxRate-Modell auskommentiert, weil es
        # von der DB gesetzt wird. Wenn es von der DB gesetzt wird und ein Timestamp ist,
        # ist dieser Block nützlich. Wenn es kein 'created_at'-Feld in deinem Django-Modell gibt,
        # dann entferne 'created_at_local' aus list_display und diese Methode.
        # Da deine DB-Tabelle 'created_at timestamp NULL DEFAULT current_timestamp()' hat
        # und dein Django FxRate-Modell kein explizites 'created_at'-Feld hat (es sei denn du hast es
        # wieder hinzugefügt), wird Django dieses Feld nicht direkt kennen.
        # Fürs Erste lasse ich es drin, falls du es doch modelliert hast.
        # Wenn du kein 'created_at' im Django-Modell hast, ersetze es in list_display
        # durch ein anderes Feld oder lasse es weg.
        if hasattr(obj, 'created_at') and obj.created_at:
            return obj.created_at.astimezone(admin.utils.timezone.get_current_timezone()).strftime('%Y-%m-%d %H:%M:%S')
        return None
    created_at_local.admin_order_field = 'created_at' # Erlaubt Sortierung nach created_at
    created_at_local.short_description = 'Erstellt am (Lokal)'


# Registriere das FxRate-Modell mit der FxRateAdmin-Klasse
admin.site.register(FxRate, FxRateAdmin)