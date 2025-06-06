# /opt/easyportfolio_django_app/portfolio_app/views.py

import json
import datetime
import pandas as pd
import numpy as np 
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.contrib import messages
from django.utils import timezone
from django.db import IntegrityError, transaction, models as django_models
from .models import Security, HistoricalPrice, Dividend, Split, Portfolio, TargetWeight 
from decimal import Decimal 
from django.contrib.auth.decorators import login_required
from django.forms import model_to_dict 
from django.conf import settings 
from . import api_clients 
from .utils import save_historical_prices_from_df, save_dividends_from_df, save_splits_from_df
from .kpi_calculator import calculate_all_kpis
import logging

logger = logging.getLogger(__name__) 


# --- portfolio_startseite ---

@login_required
def portfolio_startseite(request):
    wp_count = Security.objects.count()
    context = {
        'dynamischer_text_aus_view': "Willkommen im Maschinenraum!",
        'aktuelle_stimmung': "euphorisch",
        'wp_count': wp_count,
    }
    return render(request, 'portfolio_app/portfolio_start.html', context)


# --- einzel_wp_ansicht ---

# @login_required 
def einzel_wp_ansicht(request):
    kontext_daten = {
        'seitentitel': 'Einzelnes Wertpapier Analyse',
        'wertpapiere': [],
        'benchmarks': [],
        'ausgewaehltes_wp_id': None,
        'ausgewaehlter_benchmark_id': 0, # Default zu 0
        'ausgewaehltes_wp_obj': None,
        'kursdaten_df': None, 
        'fehler_kursdaten': None,
        'von_datum_str': (datetime.date.today() - datetime.timedelta(days=5*365)).strftime('%Y-%m-%d'),
        'bis_datum_str': datetime.date.today().strftime('%Y-%m-%d'),
        'skala': 'linear',
        'darstellung': 'Indexiert', 
        'chart_typ': 'Linie',
        'chart_daten_json': None, 
        'zeitraum_preset_form': '5J', 
    }
    try:
        alle_wertpapiere_db = Security.objects.all().order_by('security_name')
        for wp in alle_wertpapiere_db:
            ticker = wp.ticker_symbol if wp.ticker_symbol else "N/A"
            exchange_str = f".{wp.exchange}" if wp.exchange else ""
            display_name = f"{wp.security_name} ({ticker}{exchange_str})"
            kontext_daten['wertpapiere'].append({'id': wp.security_id, 'name': display_name})
    except Exception as e:
        logger.error(f"FEHLER beim Laden der Wertpapierliste für einzel_wp_ansicht: {e}", exc_info=True)
        kontext_daten['fehler_kursdaten'] = "Fehler beim Laden der Wertpapierliste."
    
    kontext_daten['benchmarks'] = [{'id': 0, 'name': '(Kein Benchmark)'}]
    try:
        benchmark_wps = Security.objects.filter(benchmark=True).order_by('security_name')
        for bench_wp in benchmark_wps:
             kontext_daten['benchmarks'].append({'id': bench_wp.security_id, 'name': f"{bench_wp.security_name} ({bench_wp.ticker_symbol})"})
    except Exception as e:
        logger.error(f"Fehler beim Laden der Benchmarks für einzel_wp_ansicht: {e}", exc_info=True)

    if request.method == 'GET':
        selected_wp_id_str = request.GET.get('wertpapier')
        selected_bench_id_str = request.GET.get('benchmark', '0') 
        kontext_daten['skala'] = request.GET.get('skala', kontext_daten['skala'])
        kontext_daten['darstellung'] = request.GET.get('darstellung', kontext_daten['darstellung'])
        kontext_daten['chart_typ'] = request.GET.get('chart_typ', kontext_daten['chart_typ'])
        kontext_daten['zeitraum_preset_form'] = request.GET.get('zeitraum_preset', kontext_daten['zeitraum_preset_form'])
        
        min_db_date, max_db_date = datetime.date(1970, 1, 1), datetime.date.today()
        try:
            min_max_dates = HistoricalPrice.objects.aggregate(min_date=django_models.Min('price_date'), max_date=django_models.Max('price_date'))
            if min_max_dates['min_date']: min_db_date = min_max_dates['min_date']
            if min_max_dates['max_date']: max_db_date = min_max_dates['max_date']
        except Exception as e: logger.warning(f"Konnte Min/Max Datum nicht aus DB lesen (einzel_wp): {e}")

        von_datum_str_req = request.GET.get('von_datum')
        bis_datum_str_req = request.GET.get('bis_datum')

        if kontext_daten['zeitraum_preset_form'] != 'Benutzerdefiniert':
            preset = kontext_daten['zeitraum_preset_form']
            end_date_preset = max_db_date
            start_date_preset = max_db_date
            if preset == '1J': start_date_preset = end_date_preset - datetime.timedelta(days=365)
            elif preset == '3J': start_date_preset = end_date_preset - datetime.timedelta(days=3*365)
            elif preset == '5J': start_date_preset = end_date_preset - datetime.timedelta(days=5*365)
            elif preset == '10J': start_date_preset = end_date_preset - datetime.timedelta(days=10*365)
            elif preset == 'Max': start_date_preset = min_db_date
            kontext_daten['von_datum_str'] = max(start_date_preset, min_db_date).strftime('%Y-%m-%d')
            kontext_daten['bis_datum_str'] = end_date_preset.strftime('%Y-%m-%d')
        elif von_datum_str_req and bis_datum_str_req:
             kontext_daten['von_datum_str'] = von_datum_str_req
             kontext_daten['bis_datum_str'] = bis_datum_str_req
        
        try:
            start_datum = datetime.datetime.strptime(kontext_daten['von_datum_str'], '%Y-%m-%d').date()
            end_datum = datetime.datetime.strptime(kontext_daten['bis_datum_str'], '%Y-%m-%d').date()
            if start_datum >= end_datum: 
                messages.warning(request, "Startdatum war gleich oder nach Enddatum. Wurde auf Vortag des Enddatums korrigiert.")
                start_datum = end_datum - datetime.timedelta(days=1) 
                kontext_daten['von_datum_str'] = start_datum.strftime('%Y-%m-%d')
        except ValueError:
            messages.error(request, "Ungültiges Datumsformat. Standardzeitraum (5J oder Max) verwendet.")
            start_datum = max(max_db_date - datetime.timedelta(days=5*365), min_db_date)
            end_datum = max_db_date
            kontext_daten['von_datum_str'] = start_datum.strftime('%Y-%m-%d')
            kontext_daten['bis_datum_str'] = end_datum.strftime('%Y-%m-%d')
            kontext_daten['zeitraum_preset_form'] = '5J' if (max_db_date - min_db_date).days > 5*365 else 'Max'

        if selected_wp_id_str and selected_wp_id_str.isdigit():
            selected_wp_id = int(selected_wp_id_str)
            kontext_daten['ausgewaehltes_wp_id'] = selected_wp_id
            try:
                ausgewaehltes_wp = get_object_or_404(Security, pk=selected_wp_id)
                kontext_daten['ausgewaehltes_wp_obj'] = ausgewaehltes_wp
                kursdaten_query = HistoricalPrice.objects.filter(
                    security=ausgewaehltes_wp, price_date__gte=start_datum, price_date__lte=end_datum
                ).order_by('price_date').values(
                    'price_date', 'adj_close_price', 'volume', 'open_price', 'high_price', 'low_price', 'close_price'
                )
                if kursdaten_query.exists():
                    df_kurse_raw = pd.DataFrame.from_records(list(kursdaten_query))
                    if not df_kurse_raw.empty:
                        df_kurse_raw['price_date'] = pd.to_datetime(df_kurse_raw['price_date'])
                        numeric_cols = ['adj_close_price', 'volume', 'open_price', 'high_price', 'low_price', 'close_price']
                        for col_df in numeric_cols:
                            if col_df in df_kurse_raw.columns:
                                df_kurse_raw[col_df] = pd.to_numeric(df_kurse_raw[col_df], errors='coerce')
                        
                        required_cols_for_plot = ['price_date']
                        y_axis_title = f"Kurs ({ausgewaehltes_wp.currency or ''})" # Default
                        y_data_col_name = 'adj_close_price' # Default für Indexierung

                        if kontext_daten['chart_typ'] == 'Candlestick':
                            required_cols_for_plot.extend(['open_price', 'high_price', 'low_price', 'close_price'])
                        elif kontext_daten['darstellung'] == 'Originalkurs':
                             y_data_col_name = 'close_price' if 'close_price' in df_kurse_raw.columns else 'adj_close_price'
                             required_cols_for_plot.append(y_data_col_name)
                             y_axis_title = f"Originalkurs ({ausgewaehltes_wp.currency or ''})"
                        else: # Indexiert
                             required_cols_for_plot.append('adj_close_price')
                             y_axis_title = 'Indexiert auf 100'
                        
                        df_kurse_cleaned = df_kurse_raw.dropna(subset=required_cols_for_plot).copy()

                        if not df_kurse_cleaned.empty:
                            plot_values_final = df_kurse_cleaned[y_data_col_name]
                            if kontext_daten['darstellung'] == 'Indexiert':
                                first_valid_price = plot_values_final.iloc[0]
                                if pd.notna(first_valid_price) and first_valid_price != 0:
                                     plot_values_final = (plot_values_final / first_valid_price) * 100
                                else: 
                                     plot_values_final = pd.Series([100] * len(plot_values_final), index=plot_values_final.index)
                            
                            chart_data_plotly = {
                                'dates': df_kurse_cleaned['price_date'].dt.strftime('%Y-%m-%d').tolist(),
                                'adj_close': plot_values_final.tolist(),
                                'security_name': ausgewaehltes_wp.security_name,
                                'open': df_kurse_cleaned['open_price'].tolist() if 'open_price' in df_kurse_cleaned else [],
                                'high': df_kurse_cleaned['high_price'].tolist() if 'high_price' in df_kurse_cleaned else [],
                                'low': df_kurse_cleaned['low_price'].tolist() if 'low_price' in df_kurse_cleaned else [],
                                'close': df_kurse_cleaned['close_price'].tolist() if 'close_price' in df_kurse_cleaned else [],
                                'chart_typ': kontext_daten['chart_typ'],
                                'y_axis_title': y_axis_title
                            }
                            kontext_daten['chart_daten_json'] = json.dumps(chart_data_plotly)
                        else: kontext_daten['fehler_kursdaten'] = f"Keine gültigen Kursdaten für {ausgewaehltes_wp.security_name} nach Bereinigung."
                    else: kontext_daten['fehler_kursdaten'] = f"Keine Kursdaten für {ausgewaehltes_wp.security_name} im Zeitraum (DataFrame leer)."
                else: kontext_daten['fehler_kursdaten'] = f"Keine Kursdaten für {ausgewaehltes_wp.security_name} im Zeitraum (DB-Abfrage leer)."
            except Security.DoesNotExist: kontext_daten['fehler_kursdaten'] = "Ausgewähltes Wertpapier nicht gefunden."
            except Exception as e:
                logger.error(f"FEHLER beim Laden der Kursdaten für einzel_wp_ansicht: {e}", exc_info=True)
                kontext_daten['fehler_kursdaten'] = f"Unerwarteter Fehler: {str(e)[:100]}"
        
        if selected_bench_id_str and selected_bench_id_str.isdigit():
            kontext_daten['ausgewaehlter_benchmark_id'] = int(selected_bench_id_str)
            # Hier Benchmark-Logik implementieren, falls benötigt

    return render(request, 'portfolio_app/einzel_wp_ansicht.html', kontext_daten)


# --- eodhd_data_hub_view ---

@login_required 
def eodhd_data_hub_view(request):
    # (Code unverändert)
    context = {
        'page_title': 'EODHD Daten-Hub',
        'search_query': request.GET.get('query', '').strip(), 
        'search_results': None,
        'preview_item_name': None,
        'eodhd_preview_chart_json': None,
    }
    preview_ticker = request.GET.get('preview_ticker')
    preview_exchange = request.GET.get('preview_exchange')
    preview_name = request.GET.get('preview_name')
    eodhd_api_key = getattr(settings, 'EODHD_API_KEY_SETTING', None)
    if preview_ticker and preview_exchange and eodhd_api_key:
        context['preview_item_name'] = preview_name or f"{preview_ticker}.{preview_exchange}"
        logger.info(f"Lade EODHD Vorschau-Chart (volle Historie) für {preview_ticker}.{preview_exchange}")
        eodhd_preview_df = api_clients.get_eodhd_history(
            preview_ticker, preview_exchange, eodhd_api_key, 
            start_date=None, end_date=datetime.date.today()
        )
        if eodhd_preview_df is not None and not eodhd_preview_df.empty:
            if 'price_date' in eodhd_preview_df.columns and 'adj_close_price' in eodhd_preview_df.columns:
                eodhd_preview_df_cleaned = eodhd_preview_df.dropna(subset=['price_date', 'adj_close_price'])
                if not eodhd_preview_df_cleaned.empty:
                    chart_data = {
                        'dates': eodhd_preview_df_cleaned['price_date'].astype(str).tolist(),
                        'adj_close': eodhd_preview_df_cleaned['adj_close_price'].tolist(),
                        'security_name': context['preview_item_name']
                    }
                    context['eodhd_preview_chart_json'] = json.dumps(chart_data)
                else: logger.warning(f"EODHD Vorschau für {preview_ticker}.{preview_exchange}: Keine Daten nach Bereinigung.")
            else: logger.warning(f"EODHD Vorschau für {preview_ticker}.{preview_exchange}: price_date oder adj_close_price Spalte fehlt.")
        else: logger.warning(f"EODHD Vorschau für {preview_ticker}.{preview_exchange}: Keine Daten von API erhalten.")
    if context['search_query']:
        if not eodhd_api_key:
            logger.error("EODHD_API_KEY_SETTING nicht in Django settings gefunden!")
            context['search_results'] = [] 
        else:
            logger.info(f"EODHD-Suche in View gestartet für: '{context['search_query']}'")
            eodhd_results = api_clients.search_eodhd(context['search_query'], eodhd_api_key)
            processed_results = []
            if eodhd_results is not None:
                logger.info(f"{len(eodhd_results)} Ergebnisse von EODHD API erhalten für '{context['search_query']}'.")
                for item in eodhd_results: 
                    item['local_db_exists'] = False
                    item['local_db_security_id'] = None
                    item['local_db_security_name'] = None
                    item['local_db_isin_match_different_ticker'] = False
                    ticker = item.get("Ticker")
                    exchange = item.get("Exchange")
                    isin = item.get("ISIN")
                    if ticker and exchange:
                        try:
                            local_sec = Security.objects.filter(ticker_symbol__iexact=ticker, exchange__iexact=exchange).first()
                            if local_sec:
                                item['local_db_exists'] = True
                                item['local_db_security_id'] = local_sec.security_id
                                item['local_db_security_name'] = local_sec.security_name
                                if isin and local_sec.isin and local_sec.isin.upper() != isin.upper():
                                    logger.warning(f"Ticker/Exchange Match für {ticker}.{exchange} (DB ID: {local_sec.security_id}), aber ISINs weichen ab: DB='{local_sec.isin}', EODHD='{isin}'")
                        except Exception as e:
                            logger.error(f"Fehler bei DB-Abfrage für Ticker/Exchange {ticker}.{exchange}: {e}", exc_info=True)
                    if not item['local_db_exists'] and isin:
                        try:
                            local_sec_by_isin = Security.objects.filter(isin__iexact=isin).first()
                            if local_sec_by_isin:
                                item['local_db_exists'] = True 
                                item['local_db_security_id'] = local_sec_by_isin.security_id
                                item['local_db_security_name'] = local_sec_by_isin.security_name
                                if not (ticker and exchange and \
                                        local_sec_by_isin.ticker_symbol.upper() == ticker.upper() and \
                                        local_sec_by_isin.exchange and \
                                        local_sec_by_isin.exchange.upper() == exchange.upper()):
                                    item['local_db_isin_match_different_ticker'] = True
                                    logger.info(f"EODHD Ergebnis {ticker}.{exchange} (ISIN: {isin}) - ISIN in DB gefunden für anderes WP: {local_sec_by_isin.ticker_symbol}.{local_sec_by_isin.exchange or ''} (ID: {local_sec_by_isin.security_id})")
                        except Exception as e:
                            logger.error(f"Fehler bei DB-Abfrage für ISIN {isin}: {e}", exc_info=True)
                    processed_results.append(item) 
                context['search_results'] = processed_results
            else:
                logger.warning(f"Keine Ergebnisse oder Fehler von api_clients.search_eodhd für '{context['search_query']}'.")
                context['search_results'] = []
    return render(request, 'portfolio_app/eodhd_data_hub.html', context)


# --- import_eodhd_security_view ---

@login_required
def import_eodhd_security_view(request):
    # (Code unverändert)
    if request.method == 'POST':
        eodhd_name = request.POST.get('eodhd_name')
        eodhd_ticker = request.POST.get('eodhd_ticker')
        eodhd_exchange = request.POST.get('eodhd_exchange')
        eodhd_isin = request.POST.get('eodhd_isin')
        eodhd_currency = request.POST.get('eodhd_currency')
        eodhd_country = request.POST.get('eodhd_country')
        if not all([eodhd_name, eodhd_ticker, eodhd_exchange]):
            messages.error(request, "Fehler: Unvollständige Daten für den Import erhalten (Name, Ticker, Börse sind Pflicht).")
            return redirect(reverse('portfolio_app:eodhd_data_hub'))
        eodhd_api_key = getattr(settings, 'EODHD_API_KEY_SETTING', None)
        if not eodhd_api_key:
            messages.error(request, "EODHD API Key ist nicht konfiguriert. Import nicht möglich.")
            logger.error("EODHD_API_KEY_SETTING nicht in Django settings gefunden für Import!")
            return redirect(reverse('portfolio_app:eodhd_data_hub'))
        try:
            if Security.objects.filter(ticker_symbol=eodhd_ticker, exchange=eodhd_exchange).exists():
                messages.info(request, f"Information: Das Wertpapier {eodhd_ticker} ({eodhd_exchange}) existiert bereits in der Datenbank.")
            else:
                new_security = Security(
                    security_name=eodhd_name, ticker_symbol=eodhd_ticker, exchange=eodhd_exchange,
                    isin=eodhd_isin if eodhd_isin and eodhd_isin != '-' else None,
                    currency=eodhd_currency if eodhd_currency and eodhd_currency != '-' else None,
                    country=eodhd_country if eodhd_country and eodhd_country != '-' else None,
                    last_api_update=timezone.now() 
                )
                new_security.save()
                logger.info(f"Neues Wertpapier importiert: ID {new_security.security_id}, Name: {new_security.security_name}")
                messages.success(request, f"Stammdaten für '{new_security.security_name}' (ID: {new_security.security_id}) erfolgreich importiert.")
                all_data_imported_successfully = True
                logger.info(f"Lade volle Kurshistorie für {new_security.ticker_symbol}.{new_security.exchange}...")
                price_history_df = api_clients.get_eodhd_history(
                    new_security.ticker_symbol, new_security.exchange, eodhd_api_key, start_date=None
                )
                if price_history_df is not None and not price_history_df.empty:
                    _, num_prices_inserted = save_historical_prices_from_df(new_security, price_history_df)
                    messages.success(request, f"{num_prices_inserted} historische Kurse gespeichert.")
                elif price_history_df is not None: 
                    messages.info(request, "Keine historischen Kursdaten von EODHD gefunden.")
                else: 
                    messages.error(request, "Fehler beim Abrufen der historischen Kursdaten von EODHD.")
                    all_data_imported_successfully = False
                logger.info(f"Lade Dividenden für {new_security.ticker_symbol}.{new_security.exchange}...")
                dividends_df = api_clients.get_eodhd_dividends(
                    new_security.ticker_symbol, new_security.exchange, eodhd_api_key, start_date=None
                )
                if dividends_df is not None and not dividends_df.empty:
                    _, num_dividends_inserted = save_dividends_from_df(new_security, dividends_df)
                    messages.success(request, f"{num_dividends_inserted} Dividendenzahlungen gespeichert.")
                elif dividends_df is not None:
                    messages.info(request, "Keine Dividendendaten von EODHD gefunden.")
                else:
                    messages.error(request, "Fehler beim Abrufen der Dividendendaten von EODHD.")
                    all_data_imported_successfully = False
                logger.info(f"Lade Splits für {new_security.ticker_symbol}.{new_security.exchange}...")
                splits_df = api_clients.get_eodhd_splits(
                    new_security.ticker_symbol, new_security.exchange, eodhd_api_key, start_date=None
                )
                if splits_df is not None and not splits_df.empty:
                    _, num_splits_inserted = save_splits_from_df(new_security, splits_df)
                    messages.success(request, f"{num_splits_inserted} Aktiensplits gespeichert.")
                elif splits_df is not None:
                    messages.info(request, "Keine Aktiensplit-Daten von EODHD gefunden.")
                else:
                    messages.error(request, "Fehler beim Abrufen der Aktiensplit-Daten von EODHD.")
                    all_data_imported_successfully = False
                if all_data_imported_successfully:
                    new_security.last_api_update = timezone.now()
                    new_security.save(update_fields=['last_api_update'])
                    logger.info(f"last_api_update für Security ID {new_security.security_id} gesetzt nach Import aller Zeitreihen.")
        except IntegrityError as e:
            logger.error(f"IntegrityError beim Versuch, {eodhd_ticker}.{eodhd_exchange} zu speichern: {e}")
            if 'isin' in str(e).lower() and eodhd_isin and Security.objects.filter(isin=eodhd_isin).exists():
                existing_isin_owner = Security.objects.filter(isin=eodhd_isin).first()
                messages.error(request, f"DB-Fehler: ISIN '{eodhd_isin}' existiert bereits für '{existing_isin_owner.security_name}' (Ticker: {existing_isin_owner.ticker_symbol}). Import von '{eodhd_name}' nicht möglich.")
            else:
                messages.error(request, f"DB-Fehler beim Speichern von {eodhd_name}: {e}")
        except Exception as e:
            logger.error(f"Allgemeiner Fehler beim Import von {eodhd_ticker}.{eodhd_exchange}: {e}", exc_info=True)
            messages.error(request, f"Unerwarteter Fehler beim Import: {e}")
        return redirect(reverse('portfolio_app:eodhd_data_hub'))
    else:
        messages.warning(request, "Ungültige Anfragemethode für den Import.")
        return redirect(reverse('portfolio_app:eodhd_data_hub'))


# --- update_eodhd_security_view ---

@login_required
def update_eodhd_security_view(request, security_id):
    # (Code unverändert)
    if request.method == 'POST':
        security_to_update = get_object_or_404(Security, pk=security_id)
        eodhd_name_from_form = request.POST.get('eodhd_name') 
        eodhd_ticker = request.POST.get('eodhd_ticker')      
        eodhd_exchange = request.POST.get('eodhd_exchange') 
        eodhd_isin = request.POST.get('eodhd_isin')
        eodhd_currency = request.POST.get('eodhd_currency')
        eodhd_country = request.POST.get('eodhd_country')
        logger.info(f"Starte Update für Security ID: {security_id} ({security_to_update.ticker_symbol}.{security_to_update.exchange}) mit EODHD-Daten: {eodhd_ticker}.{eodhd_exchange}")
        eodhd_api_key = getattr(settings, 'EODHD_API_KEY_SETTING', None)
        if not eodhd_api_key:
            messages.error(request, "EODHD API Key ist nicht konfiguriert. Update nicht möglich.")
            logger.error(f"EODHD_API_KEY_SETTING nicht gefunden für Update von SID {security_id}")
            return redirect(reverse('portfolio_app:eodhd_data_hub'))
        try:
            updated_fields = []
            if eodhd_ticker and security_to_update.ticker_symbol != eodhd_ticker:
                security_to_update.ticker_symbol = eodhd_ticker
                updated_fields.append('ticker_symbol')
            if eodhd_exchange and security_to_update.exchange != eodhd_exchange:
                security_to_update.exchange = eodhd_exchange
                updated_fields.append('exchange')
            current_isin = security_to_update.isin if security_to_update.isin else ''
            new_isin = eodhd_isin if eodhd_isin and eodhd_isin != '-' else ''
            if new_isin != current_isin:
                if new_isin and Security.objects.filter(isin__iexact=new_isin).exclude(pk=security_id).exists():
                    conflicting_sec = Security.objects.filter(isin__iexact=new_isin).exclude(pk=security_id).first()
                    messages.error(request, f"Fehler: ISIN '{new_isin}' wird bereits von '{conflicting_sec.security_name}' (ID: {conflicting_sec.security_id}) verwendet. ISIN für '{security_to_update.security_name}' nicht geändert.")
                else:
                    security_to_update.isin = new_isin if new_isin else None
                    updated_fields.append('isin')
            if eodhd_currency and eodhd_currency != '-' and security_to_update.currency != eodhd_currency:
                security_to_update.currency = eodhd_currency
                updated_fields.append('currency')
            if eodhd_country and eodhd_country != '-' and security_to_update.country != eodhd_country:
                security_to_update.country = eodhd_country
                updated_fields.append('country')
            if updated_fields:
                if 'ticker_symbol' in updated_fields or 'exchange' in updated_fields:
                    if Security.objects.filter(ticker_symbol=security_to_update.ticker_symbol, exchange=security_to_update.exchange).exclude(pk=security_id).exists():
                        conflicting_sec_for_ticker_exchange = Security.objects.filter(ticker_symbol=security_to_update.ticker_symbol, exchange=security_to_update.exchange).exclude(pk=security_id).first()
                        messages.error(request, f"Fehler: Die Kombination Ticker '{security_to_update.ticker_symbol}' und Börse '{security_to_update.exchange}' existiert bereits für '{conflicting_sec_for_ticker_exchange.security_name}' (ID: {conflicting_sec_for_ticker_exchange.security_id}). Stammdaten nicht vollständig geändert.")
                        return redirect(reverse('portfolio_app:eodhd_data_hub')) 
                security_to_update.save() 
                messages.success(request, f"Stammdaten für '{security_to_update.security_name}' (ID: {security_id}) aktualisiert: {', '.join(updated_fields)}.")
                logger.info(f"Stammdaten für SID {security_id} aktualisiert: {updated_fields}")
            else:
                messages.info(request, f"Stammdaten für '{security_to_update.security_name}' (ID: {security_id}) waren aktuell (oder nur Name hätte sich geändert, was ignoriert wurde).")
            current_db_ticker_for_api = security_to_update.ticker_symbol
            current_db_exchange_for_api = security_to_update.exchange
            if not current_db_ticker_for_api or not current_db_exchange_for_api:
                messages.error(request, f"Fehler: Ticker oder Börse für '{security_to_update.security_name}' (ID: {security_id}) ist nach Update ungültig. Zeitreihen können nicht geladen werden.")
                logger.error(f"Update für SID {security_id} abgebrochen, da Ticker ({current_db_ticker_for_api}) oder Exchange ({current_db_exchange_for_api}) für API-Aufruf ungültig sind.")
                return redirect(reverse('portfolio_app:eodhd_data_hub'))
            all_timeseries_refreshed_successfully = True
            logger.info(f"Lade volle Kurshistorie für Update von {current_db_ticker_for_api}.{current_db_exchange_for_api}...")
            price_history_df = api_clients.get_eodhd_history(current_db_ticker_for_api, current_db_exchange_for_api, eodhd_api_key, start_date=None)
            if price_history_df is not None and not price_history_df.empty:
                _, num_prices_inserted = save_historical_prices_from_df(security_to_update, price_history_df)
                messages.success(request, f"{num_prices_inserted} historische Kurse für '{security_to_update.security_name}' aktualisiert/neu importiert.")
            elif price_history_df is not None:
                messages.info(request, f"Keine historischen Kursdaten von EODHD für '{security_to_update.security_name}' gefunden.")
                HistoricalPrice.objects.filter(security=security_to_update).delete() 
            else:
                messages.error(request, f"Fehler beim Abrufen der historischen Kursdaten von EODHD für '{security_to_update.security_name}'.")
                all_timeseries_refreshed_successfully = False
            logger.info(f"Lade Dividenden für Update von {current_db_ticker_for_api}.{current_db_exchange_for_api}...")
            dividends_df = api_clients.get_eodhd_dividends(current_db_ticker_for_api, current_db_exchange_for_api, eodhd_api_key, start_date=None)
            if dividends_df is not None and not dividends_df.empty:
                _, num_dividends_inserted = save_dividends_from_df(security_to_update, dividends_df)
                messages.success(request, f"{num_dividends_inserted} Dividendenzahlungen für '{security_to_update.security_name}' aktualisiert/neu importiert.")
            elif dividends_df is not None:
                messages.info(request, f"Keine Dividendendaten von EODHD für '{security_to_update.security_name}' gefunden.")
                Dividend.objects.filter(security=security_to_update).delete() 
            else:
                messages.error(request, f"Fehler beim Abrufen der Dividendendaten von EODHD für '{security_to_update.security_name}'.")
                all_timeseries_refreshed_successfully = False
            logger.info(f"Lade Splits für Update von {current_db_ticker_for_api}.{current_db_exchange_for_api}...")
            splits_df = api_clients.get_eodhd_splits(current_db_ticker_for_api, current_db_exchange_for_api, eodhd_api_key, start_date=None)
            if splits_df is not None and not splits_df.empty:
                _, num_splits_inserted = save_splits_from_df(security_to_update, splits_df)
                messages.success(request, f"{num_splits_inserted} Aktiensplits für '{security_to_update.security_name}' aktualisiert/neu importiert.")
            elif splits_df is not None:
                messages.info(request, f"Keine Aktiensplit-Daten von EODHD für '{security_to_update.security_name}' gefunden.")
                Split.objects.filter(security=security_to_update).delete() 
            else:
                messages.error(request, f"Fehler beim Abrufen der Aktiensplit-Daten von EODHD für '{security_to_update.security_name}'.")
                all_timeseries_refreshed_successfully = False
            if all_timeseries_refreshed_successfully:
                security_to_update.last_api_update = timezone.now()
                security_to_update.save(update_fields=['last_api_update'])
                logger.info(f"last_api_update für Security ID {security_id} gesetzt nach Refresh.")
        except IntegrityError as e:
            logger.error(f"IntegrityError beim Update von SID {security_id}: {e}")
            messages.error(request, f"Datenbankfehler beim Aktualisieren der Stammdaten für '{security_to_update.security_name}': {e}")
        except Exception as e:
            logger.error(f"Allgemeiner Fehler beim Update von SID {security_id}: {e}", exc_info=True)
            messages.error(request, f"Ein unerwarteter Fehler ist beim Update von '{security_to_update.security_name}' aufgetreten: {e}")
        return redirect(reverse('portfolio_app:eodhd_data_hub'))
    else:
        messages.warning(request, "Ungültige Anfragemethode für das Update.")
        return redirect(reverse('portfolio_app:eodhd_data_hub'))


# --- experten_portfolio_ansicht_view ---

def experten_portfolio_ansicht_view(request):
    # --- Default Benchmark (unverändert) ---
    default_benchmark_id = 0 
    try:
        acwi_benchmark = Security.objects.filter(isin__iexact="IE00B6R52259", benchmark=True).first()
        if acwi_benchmark: default_benchmark_id = acwi_benchmark.security_id
    except Exception as e: logger.error(f"Fehler beim Suchen des Default Benchmarks: {e}")

    context = {
        'seitentitel': 'Expertenportfolios',
        'experten_wps': Security.objects.none(),
        'experten_portfolios_list': Portfolio.objects.none(),
        'selected_expert_wp_ids_from_url': [],
        'selected_expert_portfolio_ids_from_url': [],
        'display_name_for_chart': "Vergleichsanalyse",
        'chart_daten_json': None,
        'fehler_kursdaten': None,
        'benchmarks': [{'id': 0, 'name': '(Kein Benchmark)'}],
        'ausgewaehlter_benchmark_id': int(request.GET.get('benchmark', default_benchmark_id)),
        'zeitraum_preset_form': request.GET.get('zeitraum_preset', '10J'),
        'von_datum_str': request.GET.get('von_datum', (datetime.date.today() - datetime.timedelta(days=10*365)).strftime('%Y-%m-%d')),
        'bis_datum_str': request.GET.get('bis_datum', datetime.date.today().strftime('%Y-%m-%d')),
        'skala': request.GET.get('skala', 'linear'),
        'darstellung': 'Indexiert', 
        'chart_typ': 'Linie',      
    }
    plotly_traces = [] 
    
    # --- Lade Stammdaten ---
    try:
        context['experten_wps'] = Security.objects.filter(expert=True).order_by('security_name')
        context['experten_portfolios_list'] = Portfolio.objects.filter(expert=True).order_by('portfolio_name')
        benchmark_wps_qs = Security.objects.filter(benchmark=True).order_by('security_name')
        for bench_wp in benchmark_wps_qs:
             context['benchmarks'].append({'id': bench_wp.security_id, 'name': f"{bench_wp.security_name} ({bench_wp.ticker_symbol})"})
    except Exception as e:
        logger.error(f"Fehler beim Laden der Experten-Daten: {e}", exc_info=True)
        messages.error(request, "Fehler beim Laden der Experten-Daten.")

    # --- Verarbeite GET-Parameter ---
    try:
        context['selected_expert_wp_ids_from_url'] = [int(id_str) for id_str in request.GET.getlist('expert_wp_id') if id_str.isdigit()]
        context['selected_expert_portfolio_ids_from_url'] = [int(id_str) for id_str in request.GET.getlist('expert_portfolio_id') if id_str.isdigit()]
    except ValueError: messages.error(request, "Ungültige IDs in der URL.") 

    # ... (komplette Datumslogik hier) ...
    min_db_date, max_db_date = datetime.date(1970,1,1), datetime.date.today()
    if HistoricalPrice.objects.exists(): # ... (Rest der Datumslogik)
        try:
            min_max_agg = HistoricalPrice.objects.aggregate(min_date=django_models.Min('price_date'), max_date=django_models.Max('price_date'))
            if min_max_agg['min_date']: min_db_date = min_max_agg['min_date']
            if min_max_agg['max_date']: max_db_date = min_max_agg['max_date']
        except Exception as e: logger.warning(f"Min/Max Datum DB (Experten-View) konnte nicht ermittelt werden: {e}")
    else: logger.warning("Keine Einträge in HistoricalPrice Tabelle, verwende Standard-Datumsbereich für Experten-View.")
    von_datum_req = request.GET.get('von_datum')
    bis_datum_req = request.GET.get('bis_datum')
    if context['zeitraum_preset_form'] != 'Benutzerdefiniert' or not von_datum_req : # Wenn kein von_datum_req, dann Preset nutzen
        preset = context['zeitraum_preset_form']
        end_date_preset = max_db_date
        start_date_preset = max_db_date 
        if preset == '1J': start_date_preset = end_date_preset - datetime.timedelta(days=365)
        elif preset == '3J': start_date_preset = end_date_preset - datetime.timedelta(days=3*365)
        elif preset == '5J': start_date_preset = end_date_preset - datetime.timedelta(days=5*365)
        elif preset == '10J': start_date_preset = end_date_preset - datetime.timedelta(days=10*365)
        elif preset == 'Max': start_date_preset = min_db_date
        context['von_datum_str'] = max(start_date_preset, min_db_date).strftime('%Y-%m-%d')
        context['bis_datum_str'] = end_date_preset.strftime('%Y-%m-%d')
    elif von_datum_req and bis_datum_req: # Nur wenn benutzerdefiniert und Daten da
        context['von_datum_str'] = von_datum_req
        context['bis_datum_str'] = bis_datum_req
    try:
        start_datum_chart = datetime.datetime.strptime(context['von_datum_str'], '%Y-%m-%d').date()
        end_datum_chart = datetime.datetime.strptime(context['bis_datum_str'], '%Y-%m-%d').date()
        if start_datum_chart >= end_datum_chart:
            messages.warning(request, "Startdatum war gleich oder nach Enddatum. Wurde auf Vortag des Enddatums korrigiert.")
            start_datum_chart = end_datum_chart - datetime.timedelta(days=1) 
            context['von_datum_str'] = start_datum_chart.strftime('%Y-%m-%d')
    except ValueError:
        messages.error(request, "Ungültiges Datumsformat. Standardzeitraum (10J oder Max) verwendet.")
        start_datum_chart = max(max_db_date - datetime.timedelta(days=10*365), min_db_date)
        end_datum_chart = max_db_date
        context['von_datum_str'] = start_datum_chart.strftime('%Y-%m-%d')
        context['bis_datum_str'] = end_datum_chart.strftime('%Y-%m-%d')
        context['zeitraum_preset_form'] = '10J' if (max_db_date - min_db_date).days > 10*365 else 'Max'


    # --- Hilfsfunktionen (aus #291, mit KPI-Integration) ---
    def _get_processed_security_series(security_obj: Security, start_date: datetime.date, end_date: datetime.date):
        prices_qs = HistoricalPrice.objects.filter(security=security_obj, price_date__gte=start_date, price_date__lte=end_date).order_by('price_date').values('price_date', 'adj_close_price')
        if not prices_qs.exists(): return None, f"Keine Kurse für {security_obj.security_name} im Zeitraum."
        df_prices = pd.DataFrame.from_records(list(prices_qs)).set_index('price_date'); df_prices.index = pd.to_datetime(df_prices.index)
        if 'adj_close_price' not in df_prices.columns or df_prices['adj_close_price'].dropna().empty: return None, f"Keine 'adj_close_price' Daten für {security_obj.security_name}."
        series_to_process = df_prices['adj_close_price'].astype(float).ffill().bfill()
        if series_to_process.empty: return None, "Leere Zeitreihe nach Vorbereitung."
        first_val = series_to_process.iloc[0]
        final_series = (series_to_process / first_val * 100) if pd.notna(first_val) and first_val != 0 else pd.Series([100.0]*len(series_to_process), index=series_to_process.index)
        if not final_series.empty: final_series.iloc[0] = 100.0
        if final_series.empty: return None, "Finale Zeitreihe ist leer."
        kpi_input_df = pd.DataFrame({'datum': final_series.index, 'close': final_series.values})
        kpis = calculate_all_kpis(kpi_input_df)
        return {
            'data_id': security_obj.pk, 'data_type': 'wp',
            'dates': final_series.index.strftime('%Y-%m-%d').tolist(),
            'values': [float(v) for v in final_series.round(4).tolist()],
            'series_name': security_obj.security_name, 'chart_type_plotly': 'line',
            'kpis': kpis 
        }, None 

    def _calculate_portfolio_performance_series(portfolio_obj: Portfolio, p_start_date: datetime.date, p_end_date: datetime.date, p_target_weights_dict: dict):
        final_series, kpis, err = None, {}, None # Default
        sec_ids_in_pf = list(p_target_weights_dict.keys())
        if not sec_ids_in_pf: return None, {}, "Portfolio hat keine Zielgewichtungen." # KPIs als leeres Dict
        kurse_qs = HistoricalPrice.objects.filter(security_id__in=sec_ids_in_pf, price_date__gte=p_start_date, price_date__lte=p_end_date).order_by('price_date', 'security_id').values('price_date', 'security_id', 'adj_close_price')
        if not kurse_qs.exists(): return None, {}, "Keine Kursdaten für Portfolio-Assets im Zeitraum."
        df_l = pd.DataFrame.from_records(list(kurse_qs)); df_l['price_date'] = pd.to_datetime(df_l['price_date'])
        prices_df_pf = df_l.pivot(index='price_date', columns='security_id', values='adj_close_price').astype(float)
        all_days = pd.date_range(start=p_start_date, end=p_end_date, freq='B'); prices_df_pf = prices_df_pf.reindex(all_days).ffill()
        daily_returns_pf = prices_df_pf.pct_change(); pf_daily_returns_list = []
        if daily_returns_pf.empty or len(daily_returns_pf) <= 1: return None, {}, "Nicht genügend Daten für Renditeberechnung (Portfolio)."
        for date_idx, row_r in daily_returns_pf.iloc[1:].iterrows():
            active_r_today = row_r.dropna(); active_sids_today = active_r_today.index.tolist()
            if not active_sids_today: pf_daily_returns_list.append(0.0); continue
            current_target_w = {sid: p_target_weights_dict[sid] for sid in active_sids_today if sid in p_target_weights_dict}
            if not current_target_w: pf_daily_returns_list.append(0.0); continue
            sum_current_target_w = sum(float(w) for w in current_target_w.values())
            if sum_current_target_w == 0: pf_daily_returns_list.append(0.0); continue
            norm_w_today = {sid: float(w)/sum_current_target_w for sid,w in current_target_w.items()}
            pf_return_today = sum(float(active_r_today[sid]) * norm_w_today[sid] for sid in active_sids_today if sid in norm_w_today)
            pf_daily_returns_list.append(pf_return_today)
        if not pf_daily_returns_list: return None, {}, "Keine täglichen Portfoliorenditen berechnet."
        pf_daily_series = pd.Series(pf_daily_returns_list, index=daily_returns_pf.index[1:]).fillna(0.0)
        if pf_daily_series.empty: return None, {}, "Portfolio-Renditeserie ist leer."
        base_day_s = pd.Series([0.0], index=[pf_daily_series.index[0] - pd.Timedelta(days=1)])
        combined_r = pd.concat([base_day_s, pf_daily_series])
        pf_perf_indexed = (1 + combined_r).cumprod() * 100; pf_perf_indexed = pf_perf_indexed.iloc[1:]
        if not pf_perf_indexed.empty: pf_perf_indexed.iloc[0] = 100.0
        final_series = pf_perf_indexed.ffill().round(4)
        if final_series.empty: return None, {}, "Finale Portfolio Serie ist leer."
        kpi_input_df = pd.DataFrame({'datum': final_series.index, 'close': final_series.values})
        kpis = calculate_all_kpis(kpi_input_df)
        return final_series, kpis, None


    item_names_for_title = []
    
    # +++ NEUE, ANGEPASSTE FARBPALETTE +++
    # Farben, die gut auf dunklem Hintergrund aussehen und deine Wünsche berücksichtigen
    CUSTOM_CHART_COLORS = [
        '#0DCAF0',  # Bootstrap Info - Cyan/Türkis
        '#20C997',  # Bootstrap Teal - Hellgrün/Türkis
        '#79A8D9',  # Helleres Stahlblau - Hellblau
        '#D63384',  # Bootstrap Pink
        '#6f42c1',  # Bootstrap Indigo - Lila
        '#FFB6C1',  # LightPink - zartes Rosa
        '#FFA07A',  # LightSalmon - dezentes Orange/Rosa
        '#CD5C5C',  # IndianRed - dezentes Rot
        '#AFEEEE',  # PaleTurquoise
        '#90EE90',  # LightGreen
        '#DA70D6',  # Orchid - Lila/Pink-Variante
        '#BCAAA4',  # Ein Graubraun / Taupe
        '#90A4AE',  # Blue Grey (helleres Grau)
        '#546E7A',  # Blue Grey (dunkleres Grau)
        '#FFD700',  # Gold (kann gut aussehen)
        '#ADFF2F'   # GreenYellow
    ]
    current_color_index = 0 


    # Experten-Wertpapiere verarbeiten
    for wp_id_int in context['selected_expert_wp_ids_from_url']:
        try:
            wp_obj = Security.objects.get(pk=wp_id_int, expert=True)
            trace_dict, err = _get_processed_security_series(wp_obj, start_datum_chart, end_datum_chart)
            if err: messages.warning(request, f"Fehler bei {wp_obj.security_name}: {err}"); continue
            if trace_dict:
                trace_dict['line_color'] = CUSTOM_CHART_COLORS[current_color_index % len(CUSTOM_CHART_COLORS)]
                plotly_traces.append(trace_dict)
                item_names_for_title.append(wp_obj.security_name)
                current_color_index += 1
        # ... (Fehlerbehandlung) ...
        except Security.DoesNotExist: messages.warning(request, f"Experten-WP mit ID {wp_id_int} nicht gefunden.")
        except Exception as e_wp: logger.error(f"Fehler Verarbeitung Experten-WP ID {wp_id_int}: {e_wp}", exc_info=True); messages.error(request, f"Fehler bei WP ID {wp_id_int}.")



    # Experten-Portfolios verarbeiten
    for pf_id_int in context['selected_expert_portfolio_ids_from_url']:
        try:
            portfolio_obj = Portfolio.objects.get(pk=pf_id_int, expert=True)
            pf_target_weights = {tw.security_id: tw.target_weight / Decimal('100.0') for tw in TargetWeight.objects.filter(portfolio=portfolio_obj, target_weight__gt=0)}
            series_data, kpis_data, err = _calculate_portfolio_performance_series(portfolio_obj, start_datum_chart, end_datum_chart, pf_target_weights)
            if err: messages.warning(request, f"Fehler bei Portfolio '{portfolio_obj.portfolio_name}': {err}"); continue
            if series_data is not None and not series_data.empty:
                assigned_color = CUSTOM_CHART_COLORS[current_color_index % len(CUSTOM_CHART_COLORS)]
                current_color_index += 1
                plotly_traces.append({
                    'data_id': portfolio_obj.pk, 'data_type': 'portfolio',
                    'dates': series_data.index.strftime('%Y-%m-%d').tolist(),
                    'values': [float(v) for v in series_data.tolist()],
                    'series_name': portfolio_obj.portfolio_name,
                    'chart_type_plotly': 'line',
                    'line_color': assigned_color,
                    'kpis': kpis_data 
                })
                item_names_for_title.append(portfolio_obj.portfolio_name)
            else: messages.warning(request, f"Keine Performance-Daten für Portfolio '{portfolio_obj.portfolio_name}'.")
        # ... (Fehlerbehandlung) ...
        except Portfolio.DoesNotExist: messages.warning(request, f"Experten-Portfolio mit ID {pf_id_int} nicht gefunden.")
        except Exception as e_pf: logger.error(f"Fehler Verarbeitung Experten-Portfolio ID {pf_id_int}: {e_pf}", exc_info=True); messages.error(request, f"Fehler bei Portfolio ID {pf_id_int}.")
            
    # Benchmark verarbeiten
    if context['ausgewaehlter_benchmark_id'] != 0:
        try:
            benchmark_obj = Security.objects.get(pk=context['ausgewaehlter_benchmark_id'])
            is_primary_selection = any(str(trace.get('data_id')) == str(benchmark_obj.pk) and trace.get('data_type') == 'wp' for trace in plotly_traces)
            if not is_primary_selection:
                trace_dict, err = _get_processed_security_series(benchmark_obj, start_datum_chart, end_datum_chart)
                if err: messages.warning(request, f"Fehler bei Benchmark '{benchmark_obj.security_name}': {err}")
                if trace_dict:
                    trace_dict['series_name'] = f"{benchmark_obj.security_name} (Benchmark)"
                    trace_dict['line_color'] = '#FFFFFF' # +++ Benchmark jetzt Weiß +++
                    trace_dict['dash_style'] = 'dash'    
                    plotly_traces.append(trace_dict)
        # ... (Fehlerbehandlung) ...
        except Security.DoesNotExist: messages.warning(request, f"Benchmark mit ID {context['ausgewaehlter_benchmark_id']} nicht gefunden.")
        except Exception as e_b: logger.error(f"Fehler Verarbeitung Benchmark ID {context['ausgewaehlter_benchmark_id']}: {e_b}", exc_info=True); messages.error(request, f"Fehler bei Benchmark ID {context['ausgewaehlter_benchmark_id']}.")

    # --- Finale JSON-Erstellung und Kontext-Aktualisierung (unverändert) ---
    if plotly_traces:
        # ... (Logik für display_name_for_chart und y_axis_title wie gehabt) ...
        if len(item_names_for_title) == 1: context['display_name_for_chart'] = item_names_for_title[0]
        elif len(item_names_for_title) > 1: context['display_name_for_chart'] = "Vergleichsanalyse"
        elif not item_names_for_title and any(t['series_name'].endswith("(Benchmark)") for t in plotly_traces):
             context['display_name_for_chart'] = next(t['series_name'] for t in plotly_traces if t['series_name'].endswith("(Benchmark)"))
        else: context['display_name_for_chart'] = "Analyse" 
        final_y_axis_title = 'Performance Indexiert (Start = 100)' # Default für Vergleiche
        if len(plotly_traces) == 1 and plotly_traces[0].get('chart_type_plotly') != 'candlestick' and context.get('darstellung') == 'Originalkurs' and context['selected_expert_wp_ids_from_url']:
            # Wenn nur ein Einzel-WP als Originalkurs dargestellt wird, spezifischen Titel verwenden
            # Die Hilfsfunktion _get_processed_security_series gibt jetzt ein dict zurück, keinen y_axis_title direkt
            # Diese Logik muss ggf. angepasst werden, wenn der Titel aus dem Trace kommen soll.
            # Fürs Erste bleibt es bei "Performance Indexiert", da Vergleiche dominieren.
            # Der spezifische y_axis_title_for_trace aus dem Trace wird im JS verwendet.
            pass


        chart_data_package = {
            'traces': plotly_traces,
            'y_axis_title': final_y_axis_title, 
            'skala': context['skala']
        }
        context['chart_daten_json'] = json.dumps(chart_data_package)
    
    elif not context['fehler_kursdaten'] and (context['selected_expert_wp_ids_from_url'] or context['selected_expert_portfolio_ids_from_url']):
        context['fehler_kursdaten'] = "Keine darstellbaren Daten für die aktuelle Auswahl gefunden."

    if context['fehler_kursdaten'] and not list(messages.get_messages(request)):
        messages.warning(request, context['fehler_kursdaten'])

    return render(request, 'portfolio_app/experten_portfolio_ansicht.html', context)


# --- portfolio_manager_view ---

@login_required
def portfolio_manager_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'save_portfolio':
            portfolio_id_str = request.POST.get('portfolio_id')
            portfolio_name = request.POST.get('portfolio_name', '').strip()
            description = request.POST.get('portfolio_description', '').strip()
            is_expert = request.POST.get('is_expert_portfolio') == 'on'
            selected_security_ids = request.POST.getlist('securities') 

            if not portfolio_name:
                messages.error(request, "Portfolioname darf nicht leer sein.")
                # (Vereinfachte Rückgabe für Fehlerfall, GET-Teil wird ohnehin ausgeführt)
                return redirect(reverse('portfolio_app:portfolio_manager'))


            if not selected_security_ids:
                messages.error(request, "Bitte mindestens ein Wertpapier auswählen.")
                return redirect(reverse('portfolio_app:portfolio_manager')) 

            total_weight = 0
            weights_to_save = {}
            for sec_id_str in selected_security_ids:
                try:
                    weight_str = request.POST.get(f'weight_{sec_id_str}', '0').replace(',', '.')
                    weight = round(float(weight_str), 4) # Erhöhe Präzision für DB (7,4)
                    if weight < 0:
                        messages.error(request, f"Gewichtung für Wertpapier ID {sec_id_str} darf nicht negativ sein.")
                        return redirect(reverse('portfolio_app:portfolio_manager')) 
                    weights_to_save[int(sec_id_str)] = weight
                    total_weight += weight
                except ValueError:
                    messages.error(request, f"Ungültige Gewichtung für Wertpapier ID {sec_id_str}.")
                    return redirect(reverse('portfolio_app:portfolio_manager')) 
            
            if abs(total_weight - 100.0) > 0.01: 
                messages.error(request, f"Die Summe der Gewichtungen muss 100% ergeben (aktuell: {total_weight:.2f}%).")
                return redirect(reverse('portfolio_app:portfolio_manager'))

            try:
                with transaction.atomic(): 
                    if portfolio_id_str: 
                        portfolio_to_edit = get_object_or_404(Portfolio, pk=int(portfolio_id_str))
                        if Portfolio.objects.filter(portfolio_name=portfolio_name).exclude(pk=portfolio_to_edit.portfolio_id).exists():
                            messages.error(request, f"Ein anderes Portfolio mit dem Namen '{portfolio_name}' existiert bereits.")
                            return redirect(reverse('portfolio_app:portfolio_manager')) 
                        
                        portfolio_to_edit.portfolio_name = portfolio_name
                        portfolio_to_edit.description = description
                        portfolio_to_edit.expert = is_expert
                        portfolio_to_edit.last_modified = timezone.now()
                        portfolio_to_edit.save()
                        
                        TargetWeight.objects.filter(portfolio=portfolio_to_edit).delete()
                        portfolio_instance = portfolio_to_edit
                        action_msg = "aktualisiert"
                    else: 
                        if Portfolio.objects.filter(portfolio_name=portfolio_name).exists():
                            messages.error(request, f"Ein Portfolio mit dem Namen '{portfolio_name}' existiert bereits.")
                            return redirect(reverse('portfolio_app:portfolio_manager')) 
                        
                        portfolio_instance = Portfolio.objects.create(
                            portfolio_name=portfolio_name,
                            description=description,
                            expert=is_expert,
                            user=request.user if request.user.is_authenticated else None
                        )
                        action_msg = "gespeichert"

                    target_weights_to_create = []
                    for sec_id, weight_val in weights_to_save.items():
                        if weight_val > 0: 
                            security_instance = get_object_or_404(Security, pk=sec_id)
                            target_weights_to_create.append(
                                TargetWeight(
                                    portfolio=portfolio_instance,
                                    security=security_instance,
                                    target_weight=weight_val # DB erwartet z.B. 50.0000
                                )
                            )
                    if target_weights_to_create:
                        TargetWeight.objects.bulk_create(target_weights_to_create)
                    
                    messages.success(request, f"Portfolio '{portfolio_instance.portfolio_name}' erfolgreich {action_msg}.")
                    logger.info(f"Portfolio ID {portfolio_instance.portfolio_id} {action_msg} mit {len(target_weights_to_create)} Gewichtungen.")

            except IntegrityError as e: 
                logger.error(f"IntegrityError beim Speichern des Portfolios: {e}", exc_info=True)
                messages.error(request, f"Datenbankfehler: {e}")
            except Exception as e:
                logger.error(f"Allgemeiner Fehler beim Speichern des Portfolios: {e}", exc_info=True)
                messages.error(request, f"Ein unerwarteter Fehler ist aufgetreten: {e}")
            
            return redirect(reverse('portfolio_app:portfolio_manager'))

        elif action == 'delete_portfolio':
            portfolio_id_to_delete_str = request.POST.get('portfolio_id_to_delete')
            if portfolio_id_to_delete_str and portfolio_id_to_delete_str.isdigit():
                portfolio_id_to_delete = int(portfolio_id_to_delete_str)
                try:
                    portfolio_to_delete = get_object_or_404(Portfolio, pk=portfolio_id_to_delete)
                    deleted_name = portfolio_to_delete.portfolio_name
                    portfolio_to_delete.delete()
                    messages.success(request, f"Portfolio '{deleted_name}' wurde erfolgreich gelöscht.")
                    logger.info(f"Portfolio ID {portfolio_id_to_delete} ('{deleted_name}') gelöscht.")
                except Exception as e:
                    logger.error(f"Fehler beim Löschen von Portfolio ID {portfolio_id_to_delete}: {e}", exc_info=True)
                    messages.error(request, f"Fehler beim Löschen des Portfolios: {e}")
            else:
                messages.error(request, "Ungültige Portfolio-ID zum Löschen.")
            return redirect(reverse('portfolio_app:portfolio_manager'))

    all_securities = Security.objects.all().order_by('security_name')
    saved_portfolios_qs = Portfolio.objects.prefetch_related('target_weights', 'target_weights__security').order_by('portfolio_name')
    
    saved_portfolios_list_with_holdings = []
    for pf in saved_portfolios_qs:
        holdings_data_for_template = []
        pf_holdings_dict_for_json = {}
        # Sortierung nach Gewichtung (absteigend), dann Name (aufsteigend)
        sorted_holdings = sorted(
            pf.target_weights.all(), 
            key=lambda h: (-h.target_weight, h.security.security_name)
        )
        for h in sorted_holdings:
            holdings_data_for_template.append({
                'name': h.security.security_name,
                'ticker': h.security.ticker_symbol,
                'exchange': h.security.exchange,
                'weight': f"{h.target_weight:.1f}" # Anzeige mit einer Nachkommastelle
            })
            # Für JS: Gewichtung mit 2 Nachkommastellen, passend zum Input-Feld
            pf_holdings_dict_for_json[str(h.security.security_id)] = f"{h.target_weight:.2f}" 
        
        saved_portfolios_list_with_holdings.append({
            'portfolio_id': pf.portfolio_id,
            'portfolio_name': pf.portfolio_name,
            'description': pf.description,
            'creation_date': pf.creation_date,
            'last_modified': pf.last_modified,
            'expert': pf.expert,
            'display_holdings': holdings_data_for_template,
            'json_holdings': json.dumps(pf_holdings_dict_for_json)
        })

    form_data_context = {
        'portfolio_name': '', 'description': '', 'is_expert': False,
        'selected_security_ids_str_list': [], 
        'weights_for_template': {} 
    }

    context = {
        'seitentitel': 'Portfolio Manager',
        'all_securities_for_form': all_securities,
        'saved_portfolios_list': saved_portfolios_list_with_holdings,
        'form_data': form_data_context, 
    }
    return render(request, 'portfolio_app/portfolio_manager.html', context)


# --- portfolio_vergleich_view ---

def portfolio_vergleich_ansicht_view(request):
    # Initialisiere Kontextdaten, ähnlich zur Experten-Ansicht
    # aber mit Listen für ALLE Portfolios und Wertpapiere für die neuen Filter
    
    default_benchmark_id = 0 
    try:
        acwi_benchmark = Security.objects.filter(isin__iexact="IE00B6R52259", benchmark=True).first()
        if acwi_benchmark: default_benchmark_id = acwi_benchmark.security_id
    except Exception as e: logger.error(f"Fehler beim Suchen des Default Benchmarks (Vergleichs-View): {e}")

    context = {
        'seitentitel': 'Portfolio-Vergleich', # Neuer Titel
        'all_portfolios_for_select': Portfolio.objects.all().order_by('portfolio_name'), # Alle Portfolios
        'all_securities_for_select': Security.objects.filter(benchmark=False).order_by('security_name'), # Alle WPs (ohne Benchmarks, die separat gewählt werden)
        
        'selected_portfolio_ids_from_url': [], # Für die Vorauswahl der Filter
        'selected_security_ids_from_url': [],  # Für die Vorauswahl der Filter
        
        'display_name_for_chart': "Vergleichsanalyse",
        'chart_daten_json': None,
        'fehler_kursdaten': None,
        'benchmarks': [{'id': 0, 'name': '(Kein Benchmark)'}],
        'ausgewaehlter_benchmark_id': int(request.GET.get('benchmark', default_benchmark_id)),
        'zeitraum_preset_form': request.GET.get('zeitraum_preset', '10J'),
        'von_datum_str': request.GET.get('von_datum', (datetime.date.today() - datetime.timedelta(days=10*365)).strftime('%Y-%m-%d')),
        'bis_datum_str': request.GET.get('bis_datum', datetime.date.today().strftime('%Y-%m-%d')),
        'skala': request.GET.get('skala', 'linear'),
    }
    plotly_traces = []

    # Benchmark-Liste füllen
    try:
        benchmark_wps_qs = Security.objects.filter(benchmark=True).order_by('security_name')
        for bench_wp in benchmark_wps_qs:
             context['benchmarks'].append({'id': bench_wp.security_id, 'name': f"{bench_wp.security_name} ({bench_wp.ticker_symbol})"})
    except Exception as e:
        logger.error(f"Fehler beim Laden der Benchmark-Liste (Vergleichs-View): {e}", exc_info=True)

    # --- Verarbeite GET-Parameter für die Auswahl ---
    try:
        # Parameter-Namen für die neue Seite, z.B. 'vergleich_portfolios' und 'vergleich_securities'
        context['selected_portfolio_ids_from_url'] = [int(id_str) for id_str in request.GET.getlist('vergleich_portfolios') if id_str.isdigit()]
        context['selected_security_ids_from_url'] = [int(id_str) for id_str in request.GET.getlist('vergleich_securities') if id_str.isdigit()]
    except ValueError: messages.error(request, "Ungültige IDs in der URL für Vergleichsseite.")

    # --- Datumslogik (kann von experten_portfolio_ansicht_view übernommen werden) ---
    min_db_date, max_db_date = datetime.date(1970,1,1), datetime.date.today()
    # ... (komplette Datumslogik hier einfügen, wie in experten_portfolio_ansicht_view) ...
    # Diese Logik bestimmt start_datum_chart und end_datum_chart
    if HistoricalPrice.objects.exists():
        # ... (Min/Max Datum Ermittlung)
        pass # Platzhalter für die volle Logik
    # ... (Verarbeitung von von_datum_req, bis_datum_req und Presets)
    # Am Ende sollten start_datum_chart und end_datum_chart definiert sein.
    # Beispielhaft hier nur die Initialwerte, damit die View lauffähig ist:
    start_datum_chart = datetime.datetime.strptime(context['von_datum_str'], '%Y-%m-%d').date()
    end_datum_chart = datetime.datetime.strptime(context['bis_datum_str'], '%Y-%m-%d').date()
    if start_datum_chart >= end_datum_chart:
        start_datum_chart = end_datum_chart - datetime.timedelta(days=1)


    # --- PLATZHALTER FÜR DATENVERARBEITUNG (kommt in Schritt 2) ---
    # Hier würde die Logik stehen, um für jede ID in:
    # context['selected_portfolio_ids_from_url']
    # context['selected_security_ids_from_url']
    # context['ausgewaehlter_benchmark_id']
    # die Performance-Daten zu berechnen und plotly_traces zu füllen.
    
    # Beispielhafte Dummy-Daten, damit der Chart-Teil im Template nicht komplett leer ist
    if context['selected_portfolio_ids_from_url'] or context['selected_security_ids_from_url'] or context['ausgewaehlter_benchmark_id'] != 0:
        # Nur eine Beispiel-Trace, damit die JS-Logik etwas zum Verarbeiten hat
        # Im nächsten Schritt wird dies durch die echte Datenverarbeitung ersetzt
        dummy_dates = [(start_datum_chart + datetime.timedelta(days=x)).strftime('%Y-%m-%d') for x in range(30)]
        dummy_values = [100 + x*0.1 for x in range(30)]
        
        if context['selected_portfolio_ids_from_url']:
            portfolio_obj_dummy = Portfolio.objects.filter(pk__in=context['selected_portfolio_ids_from_url']).first()
            if portfolio_obj_dummy:
                 plotly_traces.append({
                    'dates': dummy_dates, 'values': dummy_values, 
                    'series_name': f"{portfolio_obj_dummy.portfolio_name} (Dummy)", 'line_color': '#0DCAF0'})
        
        if context['selected_security_ids_from_url']:
            security_obj_dummy = Security.objects.filter(pk__in=context['selected_security_ids_from_url']).first()
            if security_obj_dummy:
                plotly_traces.append({
                    'dates': dummy_dates, 'values': [v + 5 for v in dummy_values], # leicht andere Werte
                    'series_name': f"{security_obj_dummy.security_name} (Dummy)", 'line_color': '#20C997'})

        if context['ausgewaehlter_benchmark_id'] != 0:
            try:
                benchmark_obj_dummy = Security.objects.get(pk=context['ausgewaehlter_benchmark_id'])
                plotly_traces.append({
                    'dates': dummy_dates, 'values': [v - 5 for v in dummy_values], 
                    'series_name': f"{benchmark_obj_dummy.security_name} (Benchmark Dummy)", 
                    'line_color': '#FFFFFF', 'dash_style': 'dash'})
            except Security.DoesNotExist:
                pass
        
        if plotly_traces:
            chart_data_package = {
                'traces': plotly_traces,
                'y_axis_title': 'Performance Indexiert (Dummy-Daten)',
                'skala': context['skala']
            }
            context['chart_daten_json'] = json.dumps(chart_data_package)
            # Keine KPIs für Dummy-Daten
        else:
            context['fehler_kursdaten'] = "Bitte Elemente für den Vergleich auswählen."

    return render(request, 'portfolio_app/portfolio_vergleich_ansicht.html', context) # Neues Template!


# /opt/easyportfolio_django_app/portfolio_app/views.py
# ... (alle anderen imports und Funktionen bleiben wie sie sind) ...
# Stelle sicher, dass calculate_all_kpis importiert ist:
# from .kpi_calculator import calculate_all_kpis (falls noch nicht global geschehen)

# Die Hilfsfunktionen aus experten_portfolio_ansicht_view werden hier wiederverwendet.
# Aus Konsistenzgründen definiere ich sie hier erneut, aber in einer echten Anwendung
# würden sie in ein utils-Modul ausgelagert.

def _get_processed_security_series_for_vergleich(security_obj: Security, start_date: datetime.date, end_date: datetime.date):
    # Diese Funktion ist eine Kopie von der in experten_portfolio_ansicht_view,
    # angepasst für die Vergleichsseite (immer indexiert, immer Linie)
    prices_qs = HistoricalPrice.objects.filter(
        security=security_obj, price_date__gte=start_date, price_date__lte=end_date
    ).order_by('price_date').values('price_date', 'adj_close_price')

    if not prices_qs.exists():
        return None, f"Keine Kurse für {security_obj.security_name} im Zeitraum."

    df_prices = pd.DataFrame.from_records(list(prices_qs)).set_index('price_date')
    df_prices.index = pd.to_datetime(df_prices.index)
    
    if 'adj_close_price' not in df_prices.columns or df_prices['adj_close_price'].dropna().empty:
        return None, f"Keine 'adj_close_price' Daten für {security_obj.security_name}."

    series_to_process = df_prices['adj_close_price'].astype(float).ffill().bfill()
    if series_to_process.empty: return None, "Leere Zeitreihe nach Vorbereitung."

    # Immer indexieren für Vergleichs-Chart
    first_val = series_to_process.iloc[0]
    final_series = (series_to_process / first_val * 100) if pd.notna(first_val) and first_val != 0 else pd.Series([100.0]*len(series_to_process), index=series_to_process.index)
    if not final_series.empty: final_series.iloc[0] = 100.0 # Exakt 100 am Start
    
    if final_series.empty: return None, "Finale Zeitreihe ist leer."
    
    kpi_input_df = pd.DataFrame({'datum': final_series.index, 'close': final_series.values})
    kpis = calculate_all_kpis(kpi_input_df) # calculate_all_kpis muss importiert sein

    return {
        'data_id': security_obj.pk, 
        'data_type': 'wp', # Kennzeichnung als Wertpapier-Trace
        'dates': final_series.index.strftime('%Y-%m-%d').tolist(),
        'values': [float(v) for v in final_series.round(4).tolist()],
        'series_name': security_obj.security_name, 
        'chart_type_plotly': 'line', # Für Vergleich immer Linie
        'kpis': kpis 
    }, None 

def _calculate_portfolio_performance_series_for_vergleich(portfolio_obj: Portfolio, p_start_date: datetime.date, p_end_date: datetime.date, p_target_weights_dict: dict):
    # Diese Funktion ist eine Kopie von der in experten_portfolio_ansicht_view
    # ... (komplette Logik hier einfügen, die (Series, KPIs, Err) zurückgibt) ...
    # Am Ende:
    # return pf_perf_indexed.ffill().round(4), kpis, None -> pf_perf_indexed ist eine Series
    # (Ich kopiere die Logik aus #296 hierher zur Vollständigkeit)
    final_series, kpis, err = None, {}, None 
    sec_ids_in_pf = list(p_target_weights_dict.keys())
    if not sec_ids_in_pf: return None, {}, "Portfolio hat keine Zielgewichtungen."
    kurse_qs = HistoricalPrice.objects.filter(security_id__in=sec_ids_in_pf, price_date__gte=p_start_date, price_date__lte=p_end_date).order_by('price_date', 'security_id').values('price_date', 'security_id', 'adj_close_price')
    if not kurse_qs.exists(): return None, {}, "Keine Kursdaten für Portfolio-Assets im Zeitraum."
    df_l = pd.DataFrame.from_records(list(kurse_qs)); df_l['price_date'] = pd.to_datetime(df_l['price_date'])
    prices_df_pf = df_l.pivot(index='price_date', columns='security_id', values='adj_close_price').astype(float)
    all_days = pd.date_range(start=p_start_date, end=p_end_date, freq='B'); prices_df_pf = prices_df_pf.reindex(all_days).ffill()
    daily_returns_pf = prices_df_pf.pct_change(); pf_daily_returns_list = []
    if daily_returns_pf.empty or len(daily_returns_pf) <= 1: return None, {}, "Nicht genügend Daten für Renditeberechnung (Portfolio)."
    for date_idx, row_r in daily_returns_pf.iloc[1:].iterrows():
        active_r_today = row_r.dropna(); active_sids_today = active_r_today.index.tolist()
        if not active_sids_today: pf_daily_returns_list.append(0.0); continue
        current_target_w = {sid: p_target_weights_dict[sid] for sid in active_sids_today if sid in p_target_weights_dict}
        if not current_target_w: pf_daily_returns_list.append(0.0); continue
        sum_current_target_w = sum(float(w) for w in current_target_w.values())
        if sum_current_target_w == 0: pf_daily_returns_list.append(0.0); continue
        norm_w_today = {sid: float(w)/sum_current_target_w for sid,w in current_target_w.items()}
        pf_return_today = sum(float(active_r_today[sid]) * norm_w_today[sid] for sid in active_sids_today if sid in norm_w_today)
        pf_daily_returns_list.append(pf_return_today)
    if not pf_daily_returns_list: return None, {}, "Keine täglichen Portfoliorenditen berechnet."
    pf_daily_series = pd.Series(pf_daily_returns_list, index=daily_returns_pf.index[1:]).fillna(0.0)
    if pf_daily_series.empty: return None, {}, "Portfolio-Renditeserie ist leer."
    base_day_s = pd.Series([0.0], index=[pf_daily_series.index[0] - pd.Timedelta(days=1)])
    combined_r = pd.concat([base_day_s, pf_daily_series])
    pf_perf_indexed = (1 + combined_r).cumprod() * 100; pf_perf_indexed = pf_perf_indexed.iloc[1:]
    if not pf_perf_indexed.empty: pf_perf_indexed.iloc[0] = 100.0
    final_series = pf_perf_indexed.ffill().round(4)
    if final_series.empty: return None, {}, "Finale Portfolio Serie ist leer."
    kpi_input_df = pd.DataFrame({'datum': final_series.index, 'close': final_series.values})
    kpis = calculate_all_kpis(kpi_input_df)
    return final_series, kpis, None


# +++ NEUE VIEW FÜR PORTFOLIO-VERGLEICH +++
def portfolio_vergleich_ansicht_view(request):
    default_benchmark_id = 0 
    try: # Default Benchmark
        acwi_benchmark = Security.objects.filter(isin__iexact="IE00B6R52259", benchmark=True).first()
        if acwi_benchmark: default_benchmark_id = acwi_benchmark.security_id
    except Exception: pass

    context = {
        'seitentitel': 'Portfolio-Vergleich',
        'all_portfolios_for_select': Portfolio.objects.all().order_by('portfolio_name'),
        'all_securities_for_select': Security.objects.filter(benchmark=False, expert=False).order_by('security_name'), # Nur "normale" WPs
        # Experten-WPs und Benchmarks werden über ihre eigenen Mechanismen angeboten (oder hier mit rein, wenn gewünscht)
        # Fürs Erste trennen wir das, um die Dropdowns übersichtlich zu halten.
        'selected_portfolio_ids_from_url': [int(id_str) for id_str in request.GET.getlist('vergleich_portfolios') if id_str.isdigit()],
        'selected_security_ids_from_url': [int(id_str) for id_str in request.GET.getlist('vergleich_securities') if id_str.isdigit()],
        'display_name_for_chart': "Vergleichsanalyse", # Wird dynamisch angepasst
        'chart_daten_json': None,
        'fehler_kursdaten': None,
        'benchmarks': [{'id': 0, 'name': '(Kein Benchmark)'}],
        'ausgewaehlter_benchmark_id': int(request.GET.get('benchmark', default_benchmark_id)),
        'zeitraum_preset_form': request.GET.get('zeitraum_preset', '10J'), # Default 10J
        'von_datum_str': request.GET.get('von_datum', (datetime.date.today() - datetime.timedelta(days=10*365)).strftime('%Y-%m-%d')),
        'bis_datum_str': request.GET.get('bis_datum', datetime.date.today().strftime('%Y-%m-%d')),
        'skala': request.GET.get('skala', 'linear'),
    }
    plotly_traces = []
    
    try: # Benchmarks für Dropdown laden
        benchmark_wps_qs = Security.objects.filter(benchmark=True).order_by('security_name')
        for bench_wp in benchmark_wps_qs:
             context['benchmarks'].append({'id': bench_wp.security_id, 'name': f"{bench_wp.security_name} ({bench_wp.ticker_symbol})"})
    except Exception as e: logger.error(f"Fehler Laden Benchmarks (Vergleich): {e}", exc_info=True)

    # Datumslogik (identisch zu experten_portfolio_ansicht_view)
    # ... (komplette Datumslogik hier einfügen, um start_datum_chart und end_datum_chart zu setzen)
    min_db_date, max_db_date = datetime.date(1970,1,1), datetime.date.today()
    if HistoricalPrice.objects.exists(): # ... (Rest der Datumslogik)
        try:
            min_max_agg = HistoricalPrice.objects.aggregate(min_date=django_models.Min('price_date'), max_date=django_models.Max('price_date'))
            if min_max_agg['min_date']: min_db_date = min_max_agg['min_date']
            if min_max_agg['max_date']: max_db_date = min_max_agg['max_date']
        except Exception as e: logger.warning(f"Min/Max Datum DB (Vergleichs-View) konnte nicht ermittelt werden: {e}")
    else: logger.warning("Keine Einträge in HistoricalPrice Tabelle, verwende Standard-Datumsbereich für Vergleichs-View.")
    von_datum_req = request.GET.get('von_datum')
    bis_datum_req = request.GET.get('bis_datum')
    if context['zeitraum_preset_form'] != 'Benutzerdefiniert' or not von_datum_req : 
        preset = context['zeitraum_preset_form']
        end_date_preset = max_db_date
        start_date_preset = max_db_date 
        if preset == '1J': start_date_preset = end_date_preset - datetime.timedelta(days=365)
        # ... (alle presets)
        elif preset == '10J': start_date_preset = end_date_preset - datetime.timedelta(days=10*365)
        elif preset == 'Max': start_date_preset = min_db_date
        context['von_datum_str'] = max(start_date_preset, min_db_date).strftime('%Y-%m-%d')
        context['bis_datum_str'] = end_date_preset.strftime('%Y-%m-%d')
    elif von_datum_req and bis_datum_req: 
        context['von_datum_str'] = von_datum_req
        context['bis_datum_str'] = bis_datum_req
    try:
        start_datum_chart = datetime.datetime.strptime(context['von_datum_str'], '%Y-%m-%d').date()
        end_datum_chart = datetime.datetime.strptime(context['bis_datum_str'], '%Y-%m-%d').date()
        if start_datum_chart >= end_datum_chart:
            messages.warning(request, "Startdatum war gleich oder nach Enddatum. Wurde auf Vortag des Enddatums korrigiert.")
            start_datum_chart = end_datum_chart - datetime.timedelta(days=1) 
            context['von_datum_str'] = start_datum_chart.strftime('%Y-%m-%d')
    except ValueError: # ... (Fallback Datumslogik)
        messages.error(request, "Ungültiges Datumsformat. Standardzeitraum (10J oder Max) verwendet.")
        start_datum_chart = max(max_db_date - datetime.timedelta(days=10*365), min_db_date)
        end_datum_chart = max_db_date
        context['von_datum_str'] = start_datum_chart.strftime('%Y-%m-%d')
        context['bis_datum_str'] = end_datum_chart.strftime('%Y-%m-%d')
        context['zeitraum_preset_form'] = '10J' if (max_db_date - min_db_date).days > 10*365 else 'Max'


    item_names_for_title = []
    CUSTOM_CHART_COLORS_VERGLEICH = ['#1f77b4', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf', '#aec7e8', '#ffbb78', '#98df8a']
    current_color_idx = 0

    # Ausgewählte Wertpapiere verarbeiten
    for wp_id in context['selected_security_ids_from_url']:
        try:
            sec_obj = Security.objects.get(pk=wp_id)
            trace_data, err = _get_processed_security_series_for_vergleich(sec_obj, start_datum_chart, end_datum_chart)
            if err: messages.warning(request, f"Fehler bei {sec_obj.security_name}: {err}"); continue
            if trace_data:
                trace_data['line_color'] = CUSTOM_CHART_COLORS_VERGLEICH[current_color_idx % len(CUSTOM_CHART_COLORS_VERGLEICH)]
                plotly_traces.append(trace_data)
                item_names_for_title.append(sec_obj.security_name)
                current_color_idx += 1
        except Security.DoesNotExist: messages.warning(request, f"Wertpapier mit ID {wp_id} nicht gefunden.")
        except Exception as e: logger.error(f"Fehler Verarbeitung WP ID {wp_id} (Vergleich): {e}", exc_info=True)

    # Ausgewählte Portfolios verarbeiten
    for pf_id in context['selected_portfolio_ids_from_url']:
        try:
            pf_obj = Portfolio.objects.get(pk=pf_id)
            pf_target_weights = {tw.security_id: tw.target_weight / Decimal('100.0') for tw in TargetWeight.objects.filter(portfolio=pf_obj, target_weight__gt=0)}
            series_data, kpis, err = _calculate_portfolio_performance_series_for_vergleich(pf_obj, start_datum_chart, end_datum_chart, pf_target_weights)
            if err: messages.warning(request, f"Fehler bei Portfolio '{pf_obj.portfolio_name}': {err}"); continue
            if series_data is not None and not series_data.empty:
                plotly_traces.append({
                    'data_id': pf_obj.pk, 'data_type': 'portfolio', # Für Konsistenz, falls benötigt
                    'dates': series_data.index.strftime('%Y-%m-%d').tolist(),
                    'values': [float(v) for v in series_data.tolist()],
                    'series_name': pf_obj.portfolio_name,
                    'chart_type_plotly': 'line',
                    'line_color': CUSTOM_CHART_COLORS_VERGLEICH[current_color_idx % len(CUSTOM_CHART_COLORS_VERGLEICH)],
                    'kpis': kpis
                })
                item_names_for_title.append(pf_obj.portfolio_name)
                current_color_idx += 1
        except Portfolio.DoesNotExist: messages.warning(request, f"Portfolio mit ID {pf_id} nicht gefunden.")
        except Exception as e: logger.error(f"Fehler Verarbeitung Portfolio ID {pf_id} (Vergleich): {e}", exc_info=True)

    # Benchmark verarbeiten
    if context['ausgewaehlter_benchmark_id'] != 0:
        try:
            benchmark_obj = Security.objects.get(pk=context['ausgewaehlter_benchmark_id'])
            # Prüfen, ob Benchmark schon als normales WP ausgewählt wurde, um Duplikate zu vermeiden
            is_already_selected_as_wp = any(str(trace.get('data_id')) == str(benchmark_obj.pk) and trace.get('data_type') == 'wp' for trace in plotly_traces)
            if not is_already_selected_as_wp:
                trace_data, err = _get_processed_security_series_for_vergleich(benchmark_obj, start_datum_chart, end_datum_chart)
                if err: messages.warning(request, f"Fehler bei Benchmark '{benchmark_obj.security_name}': {err}")
                if trace_data:
                    trace_data['series_name'] = f"{benchmark_obj.security_name} (Benchmark)"
                    trace_data['line_color'] = '#FFFFFF' # Weiß für Benchmark
                    trace_data['dash_style'] = 'dash'
                    plotly_traces.append(trace_data)
                    # Benchmark nicht zum Haupttitel hinzufügen, er ist eine Referenz
        except Security.DoesNotExist: messages.warning(request, f"Benchmark mit ID {context['ausgewaehlter_benchmark_id']} nicht gefunden.")
        except Exception as e: logger.error(f"Fehler Verarbeitung Benchmark (Vergleich): {e}", exc_info=True)

    # --- Finale JSON-Erstellung ---
    if plotly_traces:
        if len(item_names_for_title) == 1: context['display_name_for_chart'] = item_names_for_title[0]
        elif len(item_names_for_title) > 1: context['display_name_for_chart'] = "Vergleichsanalyse: " + ", ".join(item_names_for_title)
        elif not item_names_for_title and any(t.get('series_name','').endswith("(Benchmark)") for t in plotly_traces): # Nur Benchmark ausgewählt
             context['display_name_for_chart'] = next(t['series_name'] for t in plotly_traces if t.get('series_name','').endswith("(Benchmark)"))
        
        chart_data_package = {
            'traces': plotly_traces,
            'y_axis_title': 'Performance Indexiert (Start = 100)',
            'skala': context['skala']
        }
        context['chart_daten_json'] = json.dumps(chart_data_package)
    elif not context['fehler_kursdaten'] and (context['selected_portfolio_ids_from_url'] or context['selected_security_ids_from_url'] or context['ausgewaehlter_benchmark_id'] != 0):
        context['fehler_kursdaten'] = "Keine darstellbaren Daten für die aktuelle Auswahl und Zeitraum gefunden."

    if context['fehler_kursdaten'] and not list(messages.get_messages(request)):
        messages.warning(request, context['fehler_kursdaten'])
        
    return render(request, 'portfolio_app/portfolio_vergleich_ansicht.html', context)