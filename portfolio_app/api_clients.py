# /opt/easyportfolio_django_app/portfolio_app/api_clients.py

import requests
import logging
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

# Richte einen Logger für dieses Modul ein
logger = logging.getLogger(__name__) # Verwendet den Modulnamen als Logger-Namen

def search_eodhd(query: str, api_key: str) -> Optional[List[Dict]]:
    """
    Sucht nach Wertpapieren über die EODHD API.

    Args:
        query (str): Der Suchbegriff.
        api_key (str): Der EODHD API Key.

    Returns:
        Optional[List[Dict]]: Eine Liste von Dictionaries mit den Suchergebnissen
                              oder None bei einem Fehler.
    """
    if not api_key:
        logger.error("EODHD API Key ist nicht konfiguriert. Suche kann nicht durchgeführt werden.")
        return None
    if not query:
        logger.debug("Leere Suchanfrage an search_eodhd übergeben.")
        return [] # Leere Liste für leere Query zurückgeben

    search_url = f"https://eodhistoricaldata.com/api/search/{query}"
    params = {"api_token": api_key, "fmt": "json"}

    logger.info(f"Starte EODHD API-Suche für: '{query}'")
    try:
        response = requests.get(search_url, params=params, timeout=15)
        response.raise_for_status() # Löst eine HTTPError Exception für 4XX/5XX Statuscodes aus

        results = response.json()
        logger.info(
            f"EODHD Suche für '{query}' ergab {len(results) if isinstance(results, list) else 'keine Liste an'} Ergebnissen."
        )

        cleaned_results: List[Dict] = []
        if isinstance(results, list):
            for item in results:
                # Stelle sicher, dass die wichtigsten Felder vorhanden sind, bevor du sie hinzufügst
                if item.get("Code") and item.get("Exchange") and item.get("Name"):
                    cleaned_results.append(
                        {
                            "Name": item.get("Name"),
                            "Ticker": item.get("Code"),
                            "Exchange": item.get("Exchange"),
                            "Country": item.get("Country"),
                            "Currency": item.get("Currency"),
                            "ISIN": item.get("ISIN"),
                            # Du könntest hier noch weitere Felder aus dem EODHD Ergebnis übernehmen
                        }
                    )
                else:
                    logger.debug(
                        f"Überspringe EODHD Suchergebnis, da Ticker, Exchange oder Name fehlt: {item}"
                    )
        else:
            logger.warning(
                f"Unerwartetes Datenformat von der EODHD Search API empfangen (erwartet: Liste): {type(results)}"
            )
            return [] # Leere Liste bei unerwartetem Format

        return cleaned_results

    except requests.exceptions.HTTPError as http_err:
        logger.error(
            f"HTTP Fehler bei EODHD Suche für '{query}': {http_err}. Response: {response.text[:500] if response else 'N/A'}", 
            exc_info=True
        )
    except requests.exceptions.RequestException as req_err:
        logger.error(
            f"Netzwerkfehler bei EODHD Suche für '{query}': {req_err}", exc_info=True
        )
    except Exception as e:
        logger.error(
            f"Allgemeiner Fehler bei EODHD Suche für '{query}': {e}", exc_info=True
        )

    return None # Im Fehlerfall None zurückgeben


def get_eodhd_history(
    ticker: str, 
    exchange: str, 
    api_key: str, 
    start_date: Optional[date] = None, 
    end_date: Optional[date] = None
) -> Optional[pd.DataFrame]:
    """
    Ruft die historische Kurshistorie (OHLCVA) für ein bestimmtes Ticker-Symbol
    von EODHD ab und gibt sie als Pandas DataFrame zurück.

    Args:
        ticker (str): Das Ticker-Symbol.
        exchange (str): Der Börsencode (z.B. 'US', 'F', 'LSE').
        api_key (str): Der EODHD API Key.
        start_date (Optional[date]): Das Startdatum für die Historie. 
                                     Standard ist 1960-01-01.
        end_date (Optional[date]): Das Enddatum für die Historie. 
                                   Standard ist heute.

    Returns:
        Optional[pd.DataFrame]: Ein DataFrame mit den historischen Kursen
                                (Spalten: price_date, open_price, high_price, 
                                low_price, close_price, adj_close_price, volume)
                                oder None bei einem Fehler.
    """
    if not api_key:
        logger.error("get_eodhd_history: EODHD API Key ist nicht konfiguriert.")
        return None
    if not ticker or not exchange:
        logger.error("get_eodhd_history: Ticker oder Exchange nicht angegeben.")
        return None

    symbol_eod = f"{ticker}.{exchange}" # EODHD verwendet Ticker.EXCHANGE
    
    # Standardwerte für Daten, falls nicht angegeben
    # Dein Streamlit-Code verwendete date(1960,1,1) als Standard-Start
    start_date_req = start_date if start_date is not None else date(1960, 1, 1) 
    end_date_req = end_date if end_date is not None else date.today()

    eod_url = f"https://eodhistoricaldata.com/api/eod/{symbol_eod}"
    params = {
        "api_token": api_key,
        "fmt": "json",
        "period": "d", # Tägliche Daten
        "from": start_date_req.strftime("%Y-%m-%d"),
        "to": end_date_req.strftime("%Y-%m-%d"),
    }

    logger.info(
        f"Rufe EODHD Kurshistorie für '{symbol_eod}' ab (Zeitraum: {start_date_req} bis {end_date_req})..."
    )
    try:
        response = requests.get(eod_url, params=params, timeout=45) # Timeout erhöht
        response.raise_for_status()
        
        data = response.json()

        if not isinstance(data, list) or not data:
            logger.warning(
                f"Leere oder ungültige Antwort von EODHD für Kurshistorie '{symbol_eod}'. Antwort: {str(data)[:200]}..."
            )
            return pd.DataFrame() # Leeren DataFrame zurückgeben

        df = pd.DataFrame(data)
        logger.info(
            f"EODHD Kurshistorie für '{symbol_eod}': {len(df)} Zeilen Rohdaten erhalten."
        )

        # Spalten umbenennen, um mit DB-Schema übereinzustimmen (wie in deinem Streamlit-Code)
        rename_map = {
            "date": "price_date",
            "open": "open_price",
            "high": "high_price",
            "low": "low_price",
            "close": "close_price",
            "adjusted_close": "adj_close_price", # EODHD liefert 'adjusted_close'
            "volume": "volume",
        }
        df.rename(columns=rename_map, inplace=True)

        # Datentypen konvertieren und sicherstellen, dass alle Spalten da sind
        if "price_date" not in df.columns or "close_price" not in df.columns:
            logger.error(
                f"Kritische Spalten 'price_date' oder 'close_price' fehlen nach Umbenennung für '{symbol_eod}'! Rohdaten-Spalten: {df.columns.tolist()}"
            )
            return pd.DataFrame() # Leerer DataFrame bei fehlenden Pflichtspalten

        df["price_date"] = pd.to_datetime(df["price_date"], errors="coerce").dt.date
        
        num_cols = [
            "open_price", "high_price", "low_price", 
            "close_price", "adj_close_price", "volume"
        ]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                # Wenn eine erwartete Spalte fehlt, füge sie mit NaN/0 hinzu
                logger.warning(f"Spalte '{col}' fehlt in EODHD Daten für {symbol_eod}. Wird mit NaN/0 initialisiert.")
                df[col] = np.nan if col != "volume" else 0 
        
        # Sicherstellen, dass Volume ein Integer ist und NaNs mit 0 gefüllt werden
        if "volume" in df.columns:
            df["volume"] = df["volume"].fillna(0).astype(np.int64)
        else: # Sollte durch obige Logik schon da sein, aber doppelt hält besser
             df["volume"] = 0


        # Zeilen entfernen, wo price_date oder close_price (nach Konvertierung) NaN sind
        df.dropna(subset=["price_date", "close_price"], inplace=True)

        if df.empty:
            logger.warning(
                f"Für '{symbol_eod}' blieben nach der Datenbereinigung keine gültigen Kurszeilen übrig."
            )
            return pd.DataFrame()

        # Sortieren und Index zurücksetzen
        df = df.sort_values(by="price_date").reset_index(drop=True)

        # Sicherstellen, dass alle Zieldpalten existieren, auch wenn sie von der API nicht kamen
        final_cols_ordered = [
            "price_date", "open_price", "high_price", "low_price", 
            "close_price", "adj_close_price", "volume"
        ]
        for col in final_cols_ordered:
            if col not in df.columns:
                df[col] = np.nan if col != "volume" else 0
        
        logger.info(
            f"EODHD Kurshistorie für '{symbol_eod}': Datenverarbeitung erfolgreich ({len(df)} Zeilen)."
        )
        return df[final_cols_ordered] # Rückgabe mit definierter Spaltenreihenfolge

    except requests.exceptions.HTTPError as http_err:
        logger.error(
            f"HTTP Fehler beim Abrufen der EODHD Kurshistorie für '{symbol_eod}': {http_err}. Response: {response.text[:500] if 'response' in locals() and response else 'N/A'}", 
            exc_info=True
        )
    except requests.exceptions.RequestException as req_err:
        logger.error(
            f"Netzwerkfehler beim Abrufen der EODHD Kurshistorie für '{symbol_eod}': {req_err}",
            exc_info=True
        )
    except Exception as e:
        logger.error(
            f"Allgemeiner Fehler beim Verarbeiten der EODHD Kurshistorie für '{symbol_eod}': {e}",
            exc_info=True
        )
    
    return None # Im Fehlerfall None zurückgeben

def get_eodhd_dividends(
    ticker: str, 
    exchange: str, 
    api_key: str, 
    start_date: Optional[date] = None, 
    end_date: Optional[date] = None
) -> Optional[pd.DataFrame]:
    """
    Ruft die Dividendenhistorie für ein bestimmtes Ticker-Symbol von EODHD ab.

    Args:
        ticker (str): Das Ticker-Symbol.
        exchange (str): Der Börsencode.
        api_key (str): Der EODHD API Key.
        start_date (Optional[date]): Das Startdatum (basierend auf Ex-Datum). 
                                     Standard ist 1960-01-01.
        end_date (Optional[date]): Das Enddatum. Standard ist heute.

    Returns:
        Optional[pd.DataFrame]: Ein DataFrame mit den Dividendendaten oder 
                                None bei einem Fehler. Leerer DataFrame, wenn keine Dividenden.
    """
    if not api_key:
        logger.error("get_eodhd_dividends: EODHD API Key ist nicht konfiguriert.")
        return None
    if not ticker or not exchange:
        logger.error("get_eodhd_dividends: Ticker oder Exchange nicht angegeben.")
        return None

    symbol_eod = f"{ticker}.{exchange}"
    start_date_req = start_date if start_date is not None else date(1960, 1, 1)
    end_date_req = end_date if end_date is not None else date.today()

    div_url = f"https://eodhistoricaldata.com/api/div/{symbol_eod}"
    params = {
        "api_token": api_key,
        "fmt": "json",
        "from": start_date_req.strftime("%Y-%m-%d"),
        "to": end_date_req.strftime("%Y-%m-%d"),
    }

    logger.info(
        f"Rufe EODHD Dividenden für '{symbol_eod}' ab ({start_date_req} bis {end_date_req})..."
    )
    try:
        response = requests.get(div_url, params=params, timeout=20) # Etwas großzügigerer Timeout
        response.raise_for_status()
        
        data = response.json()

        if not isinstance(data, list): # EODHD gibt manchmal eine einzelne Nachricht als Dict zurück
            logger.warning(
                f"Keine gültige Dividenden-Liste von EODHD für '{symbol_eod}'. Antwort: {str(data)[:200]}..."
            )
            return pd.DataFrame() # Leeren DataFrame zurückgeben

        if not data: # Leere Liste bedeutet keine Dividenden im Zeitraum
            logger.info(f"Keine Dividendendaten für '{symbol_eod}' im Zeitraum gefunden.")
            return pd.DataFrame()

        df = pd.DataFrame(data)
        
        # Spalten umbenennen (wie in deinem Streamlit-Code)
        # EODHD gibt: date, value, currency, paymentDate, declarationDate, recordDate, period
        rename_map = {
            "date": "ex_dividend_date", # Das 'date' von EODHD ist das Ex-Dividenden-Datum
            "value": "dividend_amount",
            "currency": "dividend_currency",
            # paymentDate, declarationDate, recordDate, period behalten wir bei, falls vorhanden
        }
        df.rename(columns=rename_map, inplace=True)

        if "ex_dividend_date" not in df.columns or "dividend_amount" not in df.columns:
            logger.error(f"Wichtige Spalten 'ex_dividend_date' oder 'dividend_amount' fehlen für {symbol_eod} nach Umbenennung. Rohdaten-Spalten: {df.columns.tolist()}")
            return pd.DataFrame()

        df["ex_dividend_date"] = pd.to_datetime(df["ex_dividend_date"], errors="coerce").dt.date
        df["dividend_amount"] = pd.to_numeric(df["dividend_amount"], errors="coerce")
        
        # Sicherstellen, dass alle optionalen Spalten existieren, um Fehler zu vermeiden
        optional_cols = ["paymentDate", "declarationDate", "recordDate", "period", "dividend_currency"]
        for col in optional_cols:
            if col not in df.columns:
                df[col] = None # Oder pd.NA für konsistentere Handhabung von fehlenden Werten

        # Spalten auswählen und sortieren
        cols_to_keep = [
            "ex_dividend_date", "dividend_amount", "dividend_currency",
            "paymentDate", "declarationDate", "recordDate", "period"
        ]
        # Nur Spalten behalten, die auch wirklich im DataFrame sind
        final_cols = [col for col in cols_to_keep if col in df.columns]
        
        df = df[final_cols].sort_values(by="ex_dividend_date", ascending=False).reset_index(drop=True)
        
        logger.info(f"EODHD Dividendendaten für '{symbol_eod}' erfolgreich verarbeitet ({len(df)} Zeilen).")
        return df

    except requests.exceptions.HTTPError as http_err:
        logger.error(
            f"HTTP Fehler EODHD Dividenden '{symbol_eod}': {http_err}. Response: {response.text[:500] if 'response' in locals() and response else 'N/A'}",
            exc_info=True
        )
    except requests.exceptions.RequestException as req_err:
        logger.error(
            f"Netzwerkfehler EODHD Dividenden '{symbol_eod}': {req_err}", exc_info=True
        )
    except Exception as e:
        logger.error(f"Allgemeiner Fehler EODHD Dividenden '{symbol_eod}': {e}", exc_info=True)
        
    return None # Im Fehlerfall None zurückgeben

def get_eodhd_splits(
    ticker: str, 
    exchange: str, 
    api_key: str, 
    start_date: Optional[date] = None, 
    end_date: Optional[date] = None
) -> Optional[pd.DataFrame]:
    """
    Ruft die Aktiensplit-Historie für ein bestimmtes Ticker-Symbol von EODHD ab.

    Args:
        ticker (str): Das Ticker-Symbol.
        exchange (str): Der Börsencode.
        api_key (str): Der EODHD API Key.
        start_date (Optional[date]): Das Startdatum. Standard ist 1960-01-01.
        end_date (Optional[date]): Das Enddatum. Standard ist heute.

    Returns:
        Optional[pd.DataFrame]: Ein DataFrame mit den Splitdaten 
                                (Spalten: split_date, split_ratio) oder
                                None bei einem Fehler. Leerer DataFrame, wenn keine Splits.
    """
    if not api_key:
        logger.error("get_eodhd_splits: EODHD API Key ist nicht konfiguriert.")
        return None
    if not ticker or not exchange:
        logger.error("get_eodhd_splits: Ticker oder Exchange nicht angegeben.")
        return None

    symbol_eod = f"{ticker}.{exchange}"
    start_date_req = start_date if start_date is not None else date(1960, 1, 1)
    end_date_req = end_date if end_date is not None else date.today()

    split_url = f"https://eodhistoricaldata.com/api/splits/{symbol_eod}"
    params = {
        "api_token": api_key,
        "fmt": "json",
        "from": start_date_req.strftime("%Y-%m-%d"),
        "to": end_date_req.strftime("%Y-%m-%d"),
    }

    logger.info(
        f"Rufe EODHD Splits für '{symbol_eod}' ab ({start_date_req} bis {end_date_req})..."
    )
    try:
        response = requests.get(split_url, params=params, timeout=20)
        response.raise_for_status()
        
        data = response.json()

        if not isinstance(data, list):
            logger.warning(
                f"Keine gültige Split-Liste von EODHD für '{symbol_eod}'. Antwort: {str(data)[:200]}..."
            )
            return pd.DataFrame()

        if not data:
            logger.info(f"Keine Splitdaten für '{symbol_eod}' im Zeitraum gefunden.")
            return pd.DataFrame()

        df = pd.DataFrame(data)
        
        # EODHD liefert 'date' und 'split'
        rename_map = {
            "date": "split_date",  # Das Datum des Splits
            "split": "split_ratio" # Das Split-Verhältnis (z.B. "2:1", "1:10")
        }
        df.rename(columns=rename_map, inplace=True)

        if "split_date" not in df.columns or "split_ratio" not in df.columns:
            logger.error(f"Wichtige Spalten 'split_date' oder 'split_ratio' fehlen für {symbol_eod} nach Umbenennung. Rohdaten-Spalten: {df.columns.tolist()}")
            return pd.DataFrame()

        df["split_date"] = pd.to_datetime(df["split_date"], errors="coerce").dt.date
        # split_ratio bleibt ein String, da es Formate wie "2:1" hat.
        
        df = df[["split_date", "split_ratio"]].sort_values(by="split_date", ascending=False).reset_index(drop=True)
        
        logger.info(f"EODHD Splitdaten für '{symbol_eod}' erfolgreich verarbeitet ({len(df)} Zeilen).")
        return df

    except requests.exceptions.HTTPError as http_err:
        logger.error(
            f"HTTP Fehler EODHD Splits '{symbol_eod}': {http_err}. Response: {response.text[:500] if 'response' in locals() and response else 'N/A'}",
            exc_info=True
        )
    except requests.exceptions.RequestException as req_err:
        logger.error(
            f"Netzwerkfehler EODHD Splits '{symbol_eod}': {req_err}", exc_info=True
        )
    except Exception as e:
        logger.error(f"Allgemeiner Fehler EODHD Splits '{symbol_eod}': {e}", exc_info=True)
        
    return None # Im Fehlerfall None zurückgeben


# +++ FUNKTION für Alpha Vantage FX +++

def get_alpha_vantage_fx_rate(
    api_key: str,
    from_currency: str,
    to_currency: str
) -> Optional[Tuple[date, Decimal]]:
    """
    Ruft den aktuellen Wechselkurs für ein Währungspaar von Alpha Vantage ab.

    Args:
        api_key (str): Der Alpha Vantage API Key.
        from_currency (str): Die Basiswährung (z.B. "EUR").
        to_currency (str): Die Kurswährung (z.B. "USD").

    Returns:
        Optional[Tuple[date, Decimal]]: Ein Tupel aus (Datum des Kurses, Wechselkurs)
                                         oder None bei einem Fehler oder wenn keine Daten gefunden wurden.
    """
    if not api_key:
        logger.error("get_alpha_vantage_fx_rate: Alpha Vantage API Key ist nicht konfiguriert.")
        return None
    if not from_currency or not to_currency:
        logger.error("get_alpha_vantage_fx_rate: Basis- oder Kurswährung nicht angegeben.")
        return None

    base_url = "https://www.alphavantage.co/query"
    params = {
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_currency,
        "to_currency": to_currency,
        "apikey": api_key,
    }

    logger.info(f"Rufe Alpha Vantage FX-Rate für {from_currency}/{to_currency} ab...")
    try:
        response = requests.get(base_url, params=params, timeout=20) # Timeout für API-Anfrage
        response.raise_for_status()  # Löst HTTPError für 4XX/5XX Statuscodes

        data = response.json()
        logger.debug(f"Alpha Vantage API Antwort für {from_currency}/{to_currency}: {data}")

        if "Realtime Currency Exchange Rate" in data:
            exchange_rate_data = data["Realtime Currency Exchange Rate"]
            
            rate_str = exchange_rate_data.get("5. Exchange Rate")
            last_refreshed_str = exchange_rate_data.get("6. Last Refreshed") # Format: "2024-03-17 22:50:01"

            if not rate_str or not last_refreshed_str:
                logger.warning(f"Unvollständige Daten von Alpha Vantage für {from_currency}/{to_currency}: Rate oder Datum fehlt. Data: {exchange_rate_data}")
                return None

            try:
                exchange_rate_val = Decimal(rate_str)
                # Alpha Vantage liefert manchmal Zeitstempel mit Millisekunden, manchmal ohne.
                # Wir versuchen, beide Formate zu parsen.
                try:
                    rate_date_dt = datetime.strptime(last_refreshed_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    try: # Versuch mit Millisekunden (falls AlphaVantage das Format ändert)
                        rate_date_dt = datetime.strptime(last_refreshed_str.split('.')[0], "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        logger.error(f"Ungültiges Datumsformat von Alpha Vantage für {from_currency}/{to_currency}: '{last_refreshed_str}'")
                        return None
                
                rate_date_val = rate_date_dt.date() # Nur das Datum extrahieren

                logger.info(f"Alpha Vantage FX-Rate für {from_currency}/{to_currency} am {rate_date_val}: {exchange_rate_val}")
                return rate_date_val, exchange_rate_val

            except InvalidOperation: # Fehler bei Decimal(rate_str)
                logger.error(f"Ungültiger Wechselkurs von Alpha Vantage für {from_currency}/{to_currency}: '{rate_str}'")
                return None
            except ValueError: # Fehler bei datetime.strptime
                logger.error(f"Ungültiges Datumsformat von Alpha Vantage für {from_currency}/{to_currency}: '{last_refreshed_str}'")
                return None
        
        elif "Error Message" in data:
            logger.error(f"API Fehler von Alpha Vantage für {from_currency}/{to_currency}: {data['Error Message']}")
            return None
        elif "Information" in data: # Manchmal gibt Alpha Vantage eine Info-Nachricht zurück (z.B. bei zu vielen Anfragen)
            logger.warning(f"Info-Nachricht von Alpha Vantage für {from_currency}/{to_currency}: {data['Information']}")
            return None
        else:
            logger.warning(f"Unerwartete Antwortstruktur von Alpha Vantage für {from_currency}/{to_currency}: {data}")
            return None

    except requests.exceptions.HTTPError as http_err:
        logger.error(
            f"HTTP Fehler beim Abrufen der Alpha Vantage FX-Rate für {from_currency}/{to_currency}: {http_err}. Response: {response.text[:500] if response else 'N/A'}",
            exc_info=True
        )
    except requests.exceptions.RequestException as req_err:
        logger.error(
            f"Netzwerkfehler beim Abrufen der Alpha Vantage FX-Rate für {from_currency}/{to_currency}: {req_err}",
            exc_info=True
        )
    except Exception as e:
        logger.error(
            f"Allgemeiner Fehler beim Verarbeiten der Alpha Vantage FX-Rate für {from_currency}/{to_currency}: {e}",
            exc_info=True
        )
    
    return None
