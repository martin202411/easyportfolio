# /opt/easyportfolio_django_app/portfolio_app/utils.py

import pandas as pd
import numpy as np
from django.db import transaction, IntegrityError
from .models import Security, HistoricalPrice, Dividend, Split
import logging
from typing import Tuple, Optional
from datetime import date

logger = logging.getLogger(__name__)

def save_historical_prices_from_df(security_obj: Security, price_df: pd.DataFrame) -> Tuple[int, int]:
    """
    Speichert historische Kursdaten aus einem Pandas DataFrame für ein gegebenes 
    Security-Objekt in die HistoricalPrice-Tabelle.
    Löscht zuvor alle existierenden Kurse für dieses Wertpapier, um einen sauberen Import zu gewährleisten.

    Args:
        security_obj (Security): Das Security-Instanzobjekt.
        price_df (pd.DataFrame): DataFrame mit den Kursdaten. Erwartete Spalten sind
                                 die, die von api_clients.get_eodhd_history zurückgegeben werden
                                 (price_date, open_price, high_price, low_price, 
                                 close_price, adj_close_price, volume).

    Returns:
        tuple[int, int]: (Anzahl der zu importierenden Datensätze, Anzahl der tatsächlich importierten Datensätze)
    """
    if price_df is None or price_df.empty:
        logger.warning(f"Kein Preis-DataFrame zum Speichern für {security_obj.ticker_symbol} erhalten.")
        return 0, 0

    # Stelle sicher, dass alle erwarteten Spalten im DataFrame vorhanden sind, fülle ggf. mit NaN/0
    expected_cols = ['price_date', 'open_price', 'high_price', 'low_price', 'close_price', 'adj_close_price', 'volume']
    for col in expected_cols:
        if col not in price_df.columns:
            logger.warning(f"Spalte '{col}' fehlt im Preis-DataFrame für {security_obj.ticker_symbol}. Wird mit NaN/0 initialisiert.")
            price_df[col] = np.nan if col != 'volume' else 0
    
    # Konvertiere 'price_date' sicher zu datetime.date Objekten
    try:
        price_df['price_date'] = pd.to_datetime(price_df['price_date'], errors='coerce').dt.date
    except Exception as e:
        logger.error(f"Fehler bei der Konvertierung von 'price_date' für {security_obj.ticker_symbol}: {e}")
        return len(price_df), 0 # Anzahl der Zeilen im DF, 0 erfolgreich importiert

    # Entferne Zeilen, bei denen price_date oder close_price nach der Konvertierung ungültig (NaT/NaN) sind
    price_df.dropna(subset=['price_date', 'close_price'], inplace=True)
    
    if price_df.empty:
        logger.info(f"Preis-DataFrame für {security_obj.ticker_symbol} ist nach Bereinigung (dropna) leer.")
        return 0, 0

    historical_prices_to_create = []
    for index, row in price_df.iterrows():
        # Stelle sicher, dass numerische Werte auch wirklich numerisch sind oder None
        volume_val = row.get('volume', 0)
        if pd.isna(volume_val):
            volume_val = 0
        else:
            try:
                volume_val = int(volume_val)
            except (ValueError, TypeError):
                logger.warning(f"Ungültiger Volumenwert '{row.get('volume')}' für {security_obj.ticker_symbol} an {row['price_date']}. Setze auf 0.")
                volume_val = 0
        
        # Konvertiere NaN zu None für DecimalFields, da Django NaN nicht mag
        historical_prices_to_create.append(
            HistoricalPrice(
                security=security_obj,
                price_date=row['price_date'],
                open_price=None if pd.isna(row.get('open_price')) else row.get('open_price'),
                high_price=None if pd.isna(row.get('high_price')) else row.get('high_price'),
                low_price=None if pd.isna(row.get('low_price')) else row.get('low_price'),
                close_price=row['close_price'], # Sollte nicht NaN sein wegen dropna oben
                adj_close_price=None if pd.isna(row.get('adj_close_price')) else row.get('adj_close_price'),
                volume=volume_val
            )
        )
    
    num_to_insert = len(historical_prices_to_create)
    if not historical_prices_to_create:
        logger.info(f"Keine gültigen HistoricalPrice Objekte zum Erstellen für {security_obj.ticker_symbol}.")
        return 0, 0

    try:
        # Atomare Transaktion: Entweder alles oder nichts wird gespeichert.
        with transaction.atomic():
            # Für ein komplett neu importiertes Wertpapier löschen wir zuerst alle (evtl. alten/teilweisen) Kurseinträge,
            # um Duplikate durch den unique_together Constraint ('security', 'price_date') zu vermeiden.
            existing_prices_count = HistoricalPrice.objects.filter(security=security_obj).delete()[0]
            if existing_prices_count > 0:
                logger.info(f"{existing_prices_count} existierende Kurse für {security_obj.ticker_symbol} (ID: {security_obj.security_id}) vor Neuimport gelöscht.")

            created_objects = HistoricalPrice.objects.bulk_create(historical_prices_to_create, ignore_conflicts=False)
            # ignore_conflicts=False ist Standard und besser, da wir vorher gelöscht haben. Ein Fehler hier wäre unerwartet.
            
        logger.info(f"{len(created_objects)} historische Kurse für {security_obj.ticker_symbol} erfolgreich gespeichert.")
        return num_to_insert, len(created_objects)
    except IntegrityError as e:
        logger.error(f"IntegrityError beim Speichern historischer Kurse für {security_obj.ticker_symbol}: {e}")
        return num_to_insert, 0
    except Exception as e:
        logger.error(f"Allgemeiner Fehler beim Speichern historischer Kurse für {security_obj.ticker_symbol}: {e}", exc_info=True)
        return num_to_insert, 0
    

def save_dividends_from_df(security_obj: Security, dividends_df: pd.DataFrame) -> Tuple[int, int]:
    if dividends_df is None or dividends_df.empty:
        logger.info(f"Kein Dividenden-DataFrame zum Speichern für {security_obj.ticker_symbol} erhalten.")
        return 0, 0

    dividends_to_create = []
    valid_rows_count = 0

    # Spaltennamen im DataFrame, die von api_clients.get_eodhd_dividends kommen:
    # ex_dividend_date, dividend_amount, dividend_currency, paymentDate, declarationDate, recordDate, period
    # (paymentDate, declarationDate, recordDate haben Großbuchstaben am Anfang im EODHD DataFrame)

    for index, row in dividends_df.iterrows():
        if pd.isna(row.get('ex_dividend_date')) or pd.isna(row.get('dividend_amount')):
            logger.warning(f"Überspringe Dividendenzeile für {security_obj.ticker_symbol} aufgrund fehlender Pflichtdaten (Ex-Datum oder Betrag): {row.to_dict()}")
            continue
        
        valid_rows_count += 1
        
        dividend_data = {
            'security': security_obj,
            'ex_dividend_date': pd.to_datetime(row['ex_dividend_date']).date() if pd.notna(row['ex_dividend_date']) else None,
            'amount_per_share': None if pd.isna(row['dividend_amount']) else row['dividend_amount'],
            'payment_date': pd.to_datetime(row.get('paymentDate')).date() if pd.notna(row.get('paymentDate')) else None,
            # --- NEUE FELDER BEFÜLLEN ---
            'dividend_currency': row.get('dividend_currency'), # Kommt so aus unserem api_clients.get_eodhd_dividends
            'declaration_date': pd.to_datetime(row.get('declarationDate')).date() if pd.notna(row.get('declarationDate')) else None,
            'record_date': pd.to_datetime(row.get('recordDate')).date() if pd.notna(row.get('recordDate')) else None,
            'period': row.get('period')
        }
        
        if dividend_data['ex_dividend_date'] is None or dividend_data['amount_per_share'] is None:
            logger.warning(f"Überspringe Dividendenzeile für {security_obj.ticker_symbol} nach Konvertierung aufgrund fehlender Pflichtdaten: {dividend_data}")
            valid_rows_count -=1 
            continue

        dividends_to_create.append(Dividend(**dividend_data))

    if not dividends_to_create:
        logger.info(f"Keine gültigen Dividend-Objekte zum Erstellen für {security_obj.ticker_symbol} nach Aufbereitung.")
        return valid_rows_count, 0

    try:
        with transaction.atomic():
            existing_dividends_count = Dividend.objects.filter(security=security_obj).delete()[0]
            if existing_dividends_count > 0:
                logger.info(f"{existing_dividends_count} existierende Dividenden für {security_obj.ticker_symbol} (ID: {security_obj.security_id}) vor Neuimport gelöscht.")

            created_objects = Dividend.objects.bulk_create(dividends_to_create)
            logger.info(f"{len(created_objects)} Dividenden für {security_obj.ticker_symbol} erfolgreich gespeichert.")
            return valid_rows_count, len(created_objects)
            
    except IntegrityError as e:
        logger.error(f"IntegrityError beim Speichern von Dividenden für {security_obj.ticker_symbol}: {e}")
        return valid_rows_count, 0
    except Exception as e:
        logger.error(f"Allgemeiner Fehler beim Speichern von Dividenden für {security_obj.ticker_symbol}: {e}", exc_info=True)
        return valid_rows_count, 0


def save_splits_from_df(security_obj: Security, splits_df: pd.DataFrame) -> Tuple[int, int]:
    """
    Speichert Aktiensplit-Daten aus einem Pandas DataFrame für ein gegebenes 
    Security-Objekt in die Split-Tabelle.
    Löscht zuvor alle existierenden Split-Einträge für dieses Wertpapier.

    Args:
        security_obj (Security): Das Security-Instanzobjekt.
        splits_df (pd.DataFrame): DataFrame mit den Split-Daten. Erwartete Spalten
                                  sind 'split_date' und 'split_ratio_str' 
                                  (basierend auf api_clients.get_eodhd_splits).

    Returns:
        tuple[int, int]: (Anzahl der zu importierenden Datensätze, Anzahl der tatsächlich importierten Datensätze)
    """
    if splits_df is None or splits_df.empty:
        logger.info(f"Kein Split-DataFrame zum Speichern für {security_obj.ticker_symbol} erhalten.")
        return 0, 0

    # Erwartete Spalten im DataFrame (aus api_clients.get_eodhd_splits)
    # und wie sie im Modell heißen (hier gleich)
    expected_cols = {
        "split_date": "split_date",
        "split_ratio": "split_ratio_str" # api_clients.get_eodhd_splits liefert 'split_ratio'
                                         # unser Modellfeld heißt 'split_ratio_str'
                                         # -> wir müssen den DataFrame-Spaltennamen anpassen oder hier umbenennen
    }
    
    # Umbenennen, falls die Spalte im DataFrame 'split_ratio' heißt
    if 'split_ratio' in splits_df.columns and 'split_ratio_str' not in splits_df.columns:
        splits_df.rename(columns={'split_ratio': 'split_ratio_str'}, inplace=True)


    splits_to_create = []
    valid_rows_count = 0

    for index, row in splits_df.iterrows():
        # Pflichtfelder prüfen
        if pd.isna(row.get('split_date')) or pd.isna(row.get('split_ratio_str')) or not str(row.get('split_ratio_str')).strip():
            logger.warning(f"Überspringe Split-Zeile für {security_obj.ticker_symbol} aufgrund fehlender Pflichtdaten (Datum oder Ratio): {row.to_dict()}")
            continue
        
        valid_rows_count += 1
        
        # Daten für das Modell vorbereiten
        split_data = {
            'security': security_obj,
            'split_date': pd.to_datetime(row['split_date']).date() if pd.notna(row['split_date']) else None,
            'split_ratio_str': str(row['split_ratio_str']).strip(),
        }
        
        if split_data['split_date'] is None or not split_data['split_ratio_str']:
            logger.warning(f"Überspringe Split-Zeile für {security_obj.ticker_symbol} nach Konvertierung aufgrund fehlender Pflichtdaten: {split_data}")
            valid_rows_count -= 1
            continue

        splits_to_create.append(Split(**split_data))

    if not splits_to_create:
        logger.info(f"Keine gültigen Split-Objekte zum Erstellen für {security_obj.ticker_symbol} nach Aufbereitung.")
        return valid_rows_count, 0

    try:
        with transaction.atomic():
            # Lösche alle existierenden Splits für dieses Wertpapier, um Duplikate 
            # durch den unique_together Constraint ('security', 'split_date') zu vermeiden.
            existing_splits_count = Split.objects.filter(security=security_obj).delete()[0]
            if existing_splits_count > 0:
                logger.info(f"{existing_splits_count} existierende Splits für {security_obj.ticker_symbol} (ID: {security_obj.security_id}) vor Neuimport gelöscht.")

            created_objects = Split.objects.bulk_create(splits_to_create, ignore_conflicts=False)
            logger.info(f"{len(created_objects)} Splits für {security_obj.ticker_symbol} erfolgreich gespeichert.")
            return valid_rows_count, len(created_objects)
            
    except IntegrityError as e:
        # Sollte durch das vorherige Löschen eigentlich nicht auftreten, es sei denn, die Daten im DataFrame selbst sind nicht eindeutig pro Tag
        logger.error(f"IntegrityError beim Speichern von Splits für {security_obj.ticker_symbol}: {e}")
        return valid_rows_count, 0
    except Exception as e:
        logger.error(f"Allgemeiner Fehler beim Speichern von Splits für {security_obj.ticker_symbol}: {e}", exc_info=True)
        return valid_rows_count, 0


# +++ FUNKTION für inkrementelle Kursdaten-Updates über EODHD (Scheduled Tasks) +++

def upsert_historical_prices_from_df(security_obj: Security, price_df: pd.DataFrame) -> Tuple[int, int]:
    """
    Fügt neue historische Kursdaten aus einem Pandas DataFrame für ein gegebenes
    Security-Objekt in die HistoricalPrice-Tabelle ein oder aktualisiert bestehende.
    Primär darauf ausgelegt, nur wirklich NEUE (Datum nicht vorhanden) Kurse hinzuzufügen.

    Args:
        security_obj (Security): Das Security-Instanzobjekt.
        price_df (pd.DataFrame): DataFrame mit den Kursdaten. Erwartete Spalten
                                 sind die, die von api_clients.get_eodhd_history
                                 zurückgegeben werden.

    Returns:
        tuple[int, int]: (Anzahl der Zeilen im DataFrame nach initialer Prüfung,
                          Anzahl der tatsächlich neu erstellten oder aktualisierten Datensätze)
    """
    if price_df is None or price_df.empty:
        logger.info(f"Kein Preis-DataFrame zum Upserten für {security_obj.ticker_symbol} erhalten.")
        return 0, 0

    # Grundlegende DataFrame-Bereinigung und Spaltenprüfung (ähnlich wie in save_historical_prices_from_df)
    expected_cols = ['price_date', 'open_price', 'high_price', 'low_price', 'close_price', 'adj_close_price', 'volume']
    for col in expected_cols:
        if col not in price_df.columns:
            logger.warning(f"Spalte '{col}' fehlt im Preis-DataFrame für Upsert von {security_obj.ticker_symbol}. Wird mit NaN/0 initialisiert.")
            price_df[col] = np.nan if col != 'volume' else 0
    
    try:
        price_df['price_date'] = pd.to_datetime(price_df['price_date'], errors='coerce').dt.date
    except Exception as e:
        logger.error(f"Fehler bei der Konvertierung von 'price_date' für Upsert bei {security_obj.ticker_symbol}: {e}")
        return len(price_df), 0

    price_df.dropna(subset=['price_date', 'close_price'], inplace=True) # Wichtige Spalten müssen da sein
    
    initial_df_rows = len(price_df)
    if price_df.empty:
        logger.info(f"Preis-DataFrame für Upsert von {security_obj.ticker_symbol} ist nach Bereinigung leer.")
        return initial_df_rows, 0

    # Hole alle existierenden price_date für dieses Wertpapier, um Duplikate zu vermeiden
    # Dies ist effizienter, als für jede Zeile einzeln zu prüfen.
    existing_dates: Set[date] = set(
        HistoricalPrice.objects.filter(security=security_obj)
        .values_list('price_date', flat=True)
    )
    logger.debug(f"{len(existing_dates)} existierende Kursdaten für {security_obj.ticker_symbol} gefunden.")

    historical_prices_to_create = []
    rows_to_potentially_update = [] # Für eine optionale Update-Logik

    for index, row in price_df.iterrows():
        current_price_date = row['price_date']
        
        # Prüfen, ob das Datum bereits existiert
        if current_price_date in existing_dates:
            # Hier könnte man eine Update-Logik implementieren, falls sich z.B. adj_close ändern kann.
            # Für den Moment überspringen wir existierende Daten einfach, um nur neue hinzuzufügen.
            # rows_to_potentially_update.append(row) # Für späteres Update vormerken
            continue 

        # Vorbereitung des Objekts (ähnlich wie in save_historical_prices_from_df)
        volume_val = row.get('volume', 0)
        if pd.isna(volume_val): volume_val = 0
        else:
            try: volume_val = int(volume_val)
            except (ValueError, TypeError):
                logger.warning(f"Ungültiger Volumenwert '{row.get('volume')}' für {security_obj.ticker_symbol} an {row['price_date']} bei Upsert. Setze auf 0.")
                volume_val = 0
        
        historical_prices_to_create.append(
            HistoricalPrice(
                security=security_obj,
                price_date=current_price_date,
                open_price=None if pd.isna(row.get('open_price')) else row.get('open_price'),
                high_price=None if pd.isna(row.get('high_price')) else row.get('high_price'),
                low_price=None if pd.isna(row.get('low_price')) else row.get('low_price'),
                close_price=row['close_price'], # Sollte nicht NaN sein
                adj_close_price=None if pd.isna(row.get('adj_close_price')) else row.get('adj_close_price'),
                volume=volume_val
            )
        )

    num_actually_created = 0
    if historical_prices_to_create:
        try:
            # ignore_conflicts=True, falls es doch zu einer Race Condition käme oder
            # die Vorabprüfung nicht perfekt war. Ein Fehler hier wäre aber unerwartet.
            created_objects = HistoricalPrice.objects.bulk_create(historical_prices_to_create, ignore_conflicts=True)
            num_actually_created = len(created_objects)
            logger.info(f"{num_actually_created} NEUE historische Kurse für {security_obj.ticker_symbol} erfolgreich gespeichert.")
        except IntegrityError as e: # Sollte durch ignore_conflicts=True selten auftreten
            logger.error(f"IntegrityError beim Upserten (bulk_create) historischer Kurse für {security_obj.ticker_symbol}: {e}")
        except Exception as e:
            logger.error(f"Allgemeiner Fehler beim Upserten (bulk_create) historischer Kurse für {security_obj.ticker_symbol}: {e}", exc_info=True)
    else:
        logger.info(f"Keine neuen historischen Kurse zum Speichern für {security_obj.ticker_symbol} nach Filterung.")

    # Hier könnte man noch die 'rows_to_potentially_update' durchgehen und per update_or_create aktualisieren,
    # falls das gewünscht ist. Für den Moment lassen wir das weg.
    # num_updated = 0 (Logik dafür wäre hier)

    return initial_df_rows, num_actually_created # oder num_actually_created + num_updated