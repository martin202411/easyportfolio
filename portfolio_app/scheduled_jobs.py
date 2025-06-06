# /opt/easyportfolio_django_app/portfolio_app/scheduled_jobs.py

import logging
from datetime import date, timedelta, datetime # datetime hier auch benötigt
from django.utils import timezone
from django.conf import settings # Für API-Keys
from django.db.models import Max # Max importieren
from .models import Security, HistoricalPrice, FxRate
from . import api_clients
from . import utils 


logger = logging.getLogger(__name__)

# --- Job 1: EODHD Kursdaten aktualisieren (INKREMENTELL) ---
def fetch_eodhd_historical_prices():
    """
    Holt die EOD-Kurse inkrementell für alle Wertpapiere von EODHD.
    Prüft das letzte vorhandene Datum und lädt nur neuere Kurse.
    Läuft einmal pro Werktag.
    """
    logger.info("Starte Job: fetch_eodhd_historical_prices (inkrementell)")
    
    try:
        eodhd_api_key = settings.EODHD_API_KEY_SETTING
    except AttributeError:
        logger.error("EODHD_API_KEY nicht in Django Settings gefunden! Breche Kursdaten-Job ab.")
        return

    # Hier könntest du noch ein `is_active=True` Filter einbauen, wenn du so ein Feld im Security-Modell hättest.
    securities_to_update = Security.objects.all() 
    logger.info(f"Anzahl Wertpapiere für potenzielles Update: {securities_to_update.count()}")

    total_securities_processed = 0
    total_new_prices_saved = 0

    for security in securities_to_update:
        if not security.ticker_symbol or not security.exchange:
            logger.warning(f"Überspringe Wertpapier ID {security.security_id} ({security.security_name}), da Ticker oder Exchange fehlt.")
            continue

        logger.info(f"Verarbeite Kurse für: {security.security_name} ({security.ticker_symbol}.{security.exchange})")
        
        # 1. Letztes vorhandenes Datum für dieses Wertpapier ermitteln
        last_price_entry = HistoricalPrice.objects.filter(security=security).aggregate(max_date=Max('price_date'))
        last_date_in_db = last_price_entry.get('max_date')

        start_date_for_api_call: date
        if last_date_in_db:
            start_date_for_api_call = last_date_in_db + timedelta(days=1)
            logger.info(f"Letztes Kursdatum in DB: {last_date_in_db}. API-Abfrage startet ab: {start_date_for_api_call}")
        else:
            # Keine Kurse vorhanden, lade "möglichst viele" (ab 1950 oder API-Default)
            start_date_for_api_call = date(1950, 1, 1) # Dein Wunsch-Startdatum
            logger.info(f"Keine Kurse in DB. API-Abfrage startet ab: {start_date_for_api_call}")

        # Heutiges Datum als Enddatum für den API Call (oder API-Default)
        end_date_for_api_call = date.today()

        # Sicherstellen, dass Startdatum nicht nach Enddatum liegt (kann passieren, wenn Job heute schon lief)
        if start_date_for_api_call > end_date_for_api_call:
            logger.info(f"Startdatum {start_date_for_api_call} liegt nach Enddatum {end_date_for_api_call}. Keine neuen Daten für {security.security_name} abzurufen.")
            continue # Nächstes Wertpapier

        try:
            historical_data_df = api_clients.get_eodhd_history(
                api_key=eodhd_api_key,
                ticker=security.ticker_symbol,
                exchange=security.exchange,
                start_date=start_date_for_api_call,
                end_date=end_date_for_api_call # Explizit das Enddatum übergeben
            )

            if historical_data_df is not None and not historical_data_df.empty:
                _, num_prices_inserted = utils.upsert_historical_prices_from_df(security, historical_data_df)
                total_new_prices_saved += num_prices_inserted
                if num_prices_inserted > 0:
                    logger.info(f"{num_prices_inserted} neue Kurse für {security.security_name} gespeichert.")
                    security.last_api_update = timezone.now() # Nur aktualisieren, wenn wirklich neue Daten kamen
                    security.save(update_fields=['last_api_update'])
                else:
                    logger.info(f"Keine neuen Kursdaten von EODHD für {security.security_name} nach Filterung/Upsert.")
            elif historical_data_df is not None: # DataFrame ist leer zurückgekommen
                 logger.info(f"Keine Kursdaten von EODHD API für {security.security_name} im Zeitraum {start_date_for_api_call} bis {end_date_for_api_call} erhalten (leerer DataFrame).")
            else: # API Call hat None zurückgegeben (Fehler)
                logger.warning(f"Fehler beim Abrufen der Kursdaten von EODHD für {security.security_name}.")
            
            total_securities_processed += 1

        except Exception as e:
            logger.error(f"Schwerer Fehler beim Verarbeiten der Kurse für {security.security_name}: {e}", exc_info=True)
            # Hier könntest du weitere Fehlerbehandlung einbauen (z.B. Benachrichtigung)

    logger.info(f"Job beendet: fetch_eodhd_historical_prices. {total_securities_processed} Wertpapiere verarbeitet, {total_new_prices_saved} neue Kurse insgesamt gespeichert.")


# --- Job 2: Alpha Vantage FX Daten aktualisieren ---

def fetch_alpha_vantage_fx_rates():
    """
    Holt aktuelle FX-Kurse von Alpha Vantage für definierte Währungspaare
    und speichert sie in der Datenbank.
    Läuft einmal pro Tag.
    """
    logger.info("Starte Job: fetch_alpha_vantage_fx_rates")
    
    currency_pairs = [
        ('EUR', 'USD'),     #  1
        ('EUR', 'GBP'),     #  2
        ('EUR', 'JPY'),     #  3
        ('EUR', 'CHF'),     #  4
        ('EUR', 'DKK'),     #  5
        ('EUR', 'SEK'),     #  6
        ('EUR', 'CAD'),     #  7
        ('EUR', 'NOK'),     #  8
        ('USD', 'EUR'),     #  9
        ('BTC', 'USD'),     # 10
        ('ETH', 'USD'),     # 11
        ('SOL', 'USD'),     # 12
        ('XRP', 'USD'),     # 13
        # Weitere Paare, solange das API-Limit (25/Tag) beachtet wird
    ]
    
    try:
        api_key = settings.ALPHA_VANTAGE_API_KEY_SETTING
    except AttributeError:
        logger.error("ALPHA_VANTAGE_API_KEY nicht in Django Settings gefunden! Breche FX-Job ab.")
        return

    successful_updates = 0
    failed_updates = 0

    for base_curr, quote_curr in currency_pairs:
        logger.info(f"Versuche FX-Rate für {base_curr}/{quote_curr} von Alpha Vantage zu holen.")
        
        rate_data_tuple = api_clients.get_alpha_vantage_fx_rate(
            api_key=api_key,
            from_currency=base_curr,
            to_currency=quote_curr
        )

        if rate_data_tuple:
            rate_date_val, exchange_rate_val = rate_data_tuple
            
            try:
                obj, created = FxRate.objects.update_or_create(
                    rate_date=rate_date_val,
                    base_currency=base_curr,
                    quote_currency=quote_curr,
                    defaults={
                        'exchange_rate': exchange_rate_val,
                        'source': 'Alpha Vantage',
                    }
                )
                if created:
                    logger.info(f"FX-Rate für {base_curr}/{quote_curr} am {rate_date_val} ({exchange_rate_val}) neu erstellt.")
                else:
                    logger.info(f"FX-Rate für {base_curr}/{quote_curr} am {rate_date_val} ({exchange_rate_val}) aktualisiert.")
                successful_updates += 1
            except Exception as e:
                logger.error(f"Fehler beim Speichern der FX-Rate {base_curr}/{quote_curr} in DB: {e}", exc_info=True)
                failed_updates += 1
        else:
            logger.warning(f"Keine FX-Daten von Alpha Vantage für {base_curr}/{quote_curr} erhalten oder Fehler bei API-Abfrage.")
            failed_updates += 1

    logger.info(f"Job beendet: fetch_alpha_vantage_fx_rates. Erfolgreiche Updates: {successful_updates}, Fehlgeschlagene Updates: {failed_updates}")

