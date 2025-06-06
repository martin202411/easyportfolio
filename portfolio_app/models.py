# /opt/easyportfolio_django_app/portfolio_app/models.py

from django.db import models
from django.conf import settings # Um auf das AUTH_USER_MODEL zuzugreifen
from django.utils import timezone # Ist schon importiert, gut für Defaults

class Security(models.Model):
    security_id = models.AutoField(primary_key=True) 
    ticker_symbol = models.CharField(max_length=20, null=False, blank=False)
    isin = models.CharField(max_length=12, unique=True, null=True, blank=True) 
    security_name = models.CharField(max_length=255, null=False, blank=False)
    exchange = models.CharField(max_length=50, null=True, blank=True) 
    currency = models.CharField(max_length=3, null=True, blank=True)
    security_type = models.CharField(max_length=50, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    last_api_update = models.DateTimeField(null=True, blank=True, default=None) 
    benchmark = models.BooleanField(default=False) 
    expert = models.BooleanField(default=False)

    class Meta:
        db_table = 'wp_portf_securities' 
        verbose_name = "Wertpapier"
        verbose_name_plural = "Wertpapiere"
        ordering = ['security_name'] 
        unique_together = [['ticker_symbol', 'exchange']]

    def __str__(self):
        return f"{self.security_name} ({self.ticker_symbol}{'.' + self.exchange if self.exchange else ''})"

class HistoricalPrice(models.Model):
    price_id = models.BigAutoField(primary_key=True)  # Hier definieren wir price_id als PK!
                                                      # BigAutoField passt zu bigint AUTO_INCREMENT.
    security = models.ForeignKey(
        Security,
        on_delete=models.CASCADE,
        related_name='historical_prices',
        db_column='security_id'  # Stellt sicher, dass die richtige Spalte für den FK verwendet wird (obwohl Django es oft errät)
    )
    price_date = models.DateField(null=False, blank=False)
    open_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    high_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    low_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    close_price = models.DecimalField(max_digits=18, decimal_places=4, null=False, blank=False) # Korrigiert: NOT NULL
    adj_close_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    volume = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = 'wp_portf_historical_prices'
        verbose_name = "Historischer Kurs"
        verbose_name_plural = "Historische Kurse"
        unique_together = [['security', 'price_date']] # Entspricht dem UNIQUE KEY `idx_sec_date` in deiner DB
        ordering = ['security', 'price_date']

    def __str__(self):
        # Sicherstellen, dass self.security und self.close_price nicht None sind, bevor __str__ aufgerufen wird
        # (obwohl sie laut Modell nicht None sein sollten, außer close_price wurde vorher anders definiert)
        sec_ticker = self.security.ticker_symbol if self.security else "N/A"
        close_val = self.close_price if self.close_price is not None else "N/A"
        return f"{sec_ticker} am {self.price_date}: {close_val}"
    

class Dividend(models.Model):
    dividend_id = models.AutoField(primary_key=True)
    security = models.ForeignKey(
        Security, 
        on_delete=models.CASCADE, 
        related_name='dividends'
    )
    ex_dividend_date = models.DateField(null=False, blank=False, verbose_name="Ex-Dividende Datum")
    amount_per_share = models.DecimalField(
        max_digits=18, decimal_places=4, null=False, blank=False, 
        verbose_name="Betrag pro Aktie"
        # db_column='amount_per_share' ist nicht nötig, wenn Feldname gleich Spaltenname
    )
    payment_date = models.DateField(null=True, blank=True, verbose_name="Zahltag")

    # --- NEUE OPTIONALE FELDER ---
    dividend_currency = models.CharField(max_length=10, null=True, blank=True, verbose_name="Währung der Dividende")
    declaration_date = models.DateField(null=True, blank=True, verbose_name="Deklarationsdatum")
    record_date = models.DateField(null=True, blank=True, verbose_name="Record-Datum (Stichtag)")
    period = models.CharField(max_length=50, null=True, blank=True, verbose_name="Dividendenperiode (z.B. Quarterly)")
    # --- ENDE NEUE OPTIONALE FELDER ---

    class Meta:
        db_table = 'wp_portf_dividends'
        verbose_name = "Dividende"
        verbose_name_plural = "Dividenden"
        # Ein pragmatischer Unique Constraint. Verhindert exakt identische Einträge.
        # Die Logik in save_dividends_from_df (delete all first) ist der Hauptschutz gegen Duplikate bei Re-Import.
        unique_together = [['security', 'ex_dividend_date', 'amount_per_share']] 
        ordering = ['security', '-ex_dividend_date']

    def __str__(self):
        currency_str = f" {self.dividend_currency}" if self.dividend_currency else ""
        return f"Dividende für {self.security.ticker_symbol} am {self.ex_dividend_date}: {self.amount_per_share}{currency_str}"


class Split(models.Model):
    split_id = models.AutoField(primary_key=True) # Eigener Primärschlüssel
    security = models.ForeignKey(
        Security,
        on_delete=models.CASCADE,
        related_name='splits' # Ermöglicht Zugriff via security_obj.splits.all()
    )
    split_date = models.DateField(null=False, blank=False, verbose_name="Split-Datum")
    # Das Split-Verhältnis wird als Text gespeichert, z.B. "2:1", "1:10", "1.5:1"
    # EODHD liefert dies als String.
    split_ratio_str = models.CharField(max_length=20, null=False, blank=False, verbose_name="Split-Verhältnis (Text)")
    # Optional könnten wir hier noch Felder für 'split_from' und 'split_to' als Float/Decimal hinzufügen,
    # wenn wir das Verhältnis parsen und numerisch speichern wollen, aber für den Anfang reicht der String.

    class Meta:
        db_table = 'wp_portf_splits' # Name der Datenbanktabelle
        verbose_name = "Aktiensplit"
        verbose_name_plural = "Aktiensplits"
        # Annahme: Pro Wertpapier gibt es an einem Tag höchstens einen Split-Eintrag.
        unique_together = [['security', 'split_date']]
        ordering = ['security', '-split_date'] # Neueste zuerst pro Wertpapier

    def __str__(self):
        return f"Split für {self.security.ticker_symbol} am {self.split_date}: {self.split_ratio_str}"


class Portfolio(models.Model):
    portfolio_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        db_column='user_id',
        verbose_name="Benutzer"
    )
    portfolio_name = models.CharField(max_length=255, null=False, blank=False, verbose_name="Portfolioname")
    description = models.TextField(null=True, blank=True, verbose_name="Beschreibung")
    creation_date = models.DateTimeField(auto_now_add=True, verbose_name="Erstellungsdatum")
    last_modified = models.DateTimeField(auto_now=True, verbose_name="Zuletzt geändert")
    expert = models.BooleanField(default=False, verbose_name="Expertenportfolio")

    class Meta:
        db_table = 'wp_portf_portfolios'
        verbose_name = "Portfolio"
        verbose_name_plural = "Portfolios"
        ordering = ['portfolio_name']

    def __str__(self):
        return self.portfolio_name

    def __str__(self):
        return self.portfolio_name


class TargetWeight(models.Model):
    target_weight_id = models.AutoField(primary_key=True)
    portfolio = models.ForeignKey(
        Portfolio, 
        on_delete=models.CASCADE, # Wenn Portfolio gelöscht wird, werden auch die Gewichtungen gelöscht
        db_column='portfolio_id',
        related_name='target_weights'
    )
    security = models.ForeignKey(
        Security, 
        on_delete=models.CASCADE, # Wenn Security gelöscht wird, werden auch die Gewichtungen gelöscht
        db_column='security_id',
        related_name='target_weights'
    )
    # decimal(7,4) bedeutet 3 Stellen vor und 4 Stellen nach dem Komma (z.B. 100.0000)
    # Der Kommentar in deiner DB sagt "50.0000 für 50%".
    target_weight = models.DecimalField(
        max_digits=7, decimal_places=4, null=False, blank=False, 
        verbose_name="Zielgewichtung (%)" 
        # help_text="Gewichtung in Prozent, z.B. 50.00 für 50%" # Optionaler Hilfetext
    )

    class Meta:
        db_table = 'wp_portf_target_weights'
        verbose_name = "Zielgewichtung"
        verbose_name_plural = "Zielgewichtungen"
        # Entspricht UNIQUE KEY `unique_portfolio_security` (`portfolio_id`,`security_id`)
        unique_together = [['portfolio', 'security']]
        ordering = ['portfolio', 'security']

    def __str__(self):
        return f"{self.security.ticker_symbol} in '{self.portfolio.portfolio_name}': {self.target_weight}%"


class FxRate(models.Model):
    # Dein Primärschlüssel ist ('rate_date', 'base_currency', 'quote_currency')
    # Django benötigt standardmäßig einen einzelnen Primärschlüssel pro Modell,
    # es sei denn, man verwendet spezielle Konfigurationen (was selten gemacht wird).
    # Wenn du den zusammengesetzten PK beibehalten willst, ist das okay, aber
    # Django wird im Hintergrund einen impliziten 'id' AutoField hinzufügen, es sei denn,
    # ein Feld ist explizit als primary_key=True markiert.
    # Deine Tabellendefinition hat "PRIMARY KEY (`rate_date`,`base_currency`,`quote_currency`)"
    # Das ist als unique_together abbildbar. Django benötigt aber für ORM-Operationen
    # oft einen einzelnen PK. Es ist gängige Praxis, einen AutoField hinzuzufügen,
    # auch wenn ein anderer unique constraint existiert.
    # Für den Moment belassen wir es ohne expliziten PK hier, Django wird einen 'id' hinzufügen.
    # Alternativ: rate_id = models.AutoField(primary_key=True)

    rate_date = models.DateField(null=False, blank=False)
    base_currency = models.CharField(max_length=3, null=False, blank=False)
    quote_currency = models.CharField(max_length=3, null=False, blank=False)
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=8, null=False, blank=False)
    source = models.CharField(max_length=50, null=True, blank=True)
    # created_at wird automatisch durch die DB gesetzt (DEFAULT current_timestamp())
    # Wenn du es Django-verwaltet haben möchtest:
    # created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'wp_portf_fx_rates'
        verbose_name = "FX Wechselkurs"
        verbose_name_plural = "FX Wechselkurse"
        # Dies bildet deinen zusammengesetzten Primärschlüssel als Unique Constraint ab
        unique_together = [['rate_date', 'base_currency', 'quote_currency']]
        ordering = ['-rate_date', 'base_currency', 'quote_currency']

    def __str__(self):
        return f"{self.base_currency}/{self.quote_currency} am {self.rate_date}: {self.exchange_rate}"
    