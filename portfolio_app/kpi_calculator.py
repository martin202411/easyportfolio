# /opt/easyportfolio_django_app/portfolio_app/kpi_calculator.py

import pandas as pd
import numpy as np
from datetime import timedelta
import logging # Importiere logging

# Stelle sicher, dass ein Logger vorhanden ist, falls nicht global konfiguriert
logger = logging.getLogger(__name__)
if not logger.handlers:
    # Fallback-Konfiguration, wenn kein Handler da ist
    # In Django wird dies normalerweise zentral konfiguriert
    # logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    pass # In Django wird erwartet, dass Logging schon konfiguriert ist


def calculate_all_kpis(df_kurse: pd.DataFrame):
    """
    Berechnet Performance- und Risikokennzahlen aus einem Kurs-DataFrame.
    Der DataFrame sollte 'datum' (als index oder Spalte) und 'close' (numerisch) enthalten.
    'close' können Originalkurse oder eine indexierte Serie (Start bei 100) sein.
    """
    kennzahlen = {
        "start_datum": None, "start_kurs": np.nan,
        "end_datum": None, "end_kurs": np.nan,
        "ges_rendite": np.nan, "cagr": np.nan,
        "std_abw_d": np.nan, "varianz_d": np.nan,
        "vola_a": np.nan, # NEU: Annualisierte Volatilität
        "downside_risk_d": np.nan,
        "var95_d": np.nan,
        "sharpe_a": np.nan,
        "sortino_a": np.nan,
        "max_drawdown": np.nan, # NEU: Maximaler Drawdown
        "anzahl_tage": 0,
        "anzahl_jahre": np.nan
    }

    if df_kurse is None or df_kurse.empty or "close" not in df_kurse.columns:
        logger.warning("KPI Calc: Input DataFrame ist leer oder ungültig ('close' fehlt).")
        return kennzahlen
    
    # Stelle sicher, dass der Index ein DatetimeIndex ist, falls 'datum' eine Spalte ist
    if 'datum' in df_kurse.columns:
        df = df_kurse[['datum', 'close']].copy()
        if not pd.api.types.is_datetime64_any_dtype(df["datum"]):
            df["datum"] = pd.to_datetime(df["datum"], errors='coerce')
        df = df.set_index('datum')
    else: # Nehme an, der Index ist bereits das Datum
        df = df_kurse[['close']].copy()

    df.dropna(subset=["close"], inplace=True)
    df = df.sort_index()

    if len(df) < 2:
        logger.warning("KPI Calc: Nicht genügend Datenpunkte (< 2) nach Bereinigung.")
        if len(df) == 1:
            try:
                kennzahlen["start_datum"] = df.index[0].strftime("%Y-%m-%d")
                kennzahlen["end_datum"] = df.index[0].strftime("%Y-%m-%d")
                kennzahlen["start_kurs"] = float(df["close"].iloc[0])
                kennzahlen["end_kurs"] = float(df["close"].iloc[0])
                kennzahlen["anzahl_tage"] = 1
                kennzahlen["anzahl_jahre"] = 1 / 365.25 # Für Konsistenz, obwohl CAGR etc. NaN bleiben
            except Exception: pass
        return kennzahlen

    try:
        kennzahlen["start_datum"] = df.index[0].strftime("%Y-%m-%d")
        kennzahlen["start_kurs"] = float(df["close"].iloc[0])
        kennzahlen["end_datum"] = df.index[-1].strftime("%Y-%m-%d")
        kennzahlen["end_kurs"] = float(df["close"].iloc[-1])
        
        time_delta = df.index[-1] - df.index[0]
        kennzahlen["anzahl_tage"] = time_delta.days
        kennzahlen["anzahl_jahre"] = time_delta.days / 365.25

    except Exception as e:
        logger.error(f"KPI Calc: Fehler bei Start-/Endwerten: {e}")

    start_kurs, end_kurs = kennzahlen["start_kurs"], kennzahlen["end_kurs"]
    jahre = kennzahlen["anzahl_jahre"]

    if pd.notna(start_kurs) and pd.notna(end_kurs) and start_kurs != 0:
        try:
            kennzahlen["ges_rendite"] = (end_kurs / start_kurs) - 1
            if pd.notna(jahre) and jahre >= (1/365.25) : # Mindestens 1 Tag für CAGR
                basis_cagr = end_kurs / start_kurs
                if basis_cagr > 0: # Basis für Potenz muss positiv sein
                    kennzahlen["cagr"] = (basis_cagr ** (1 / jahre)) - 1
                else:
                    kennzahlen["cagr"] = -1.0 # Oder np.nan, wenn Start < Ende aber Basis <=0
            elif pd.notna(kennzahlen["ges_rendite"]): # Für Zeiträume < 1 Tag
                kennzahlen["cagr"] = kennzahlen["ges_rendite"]

        except Exception as e: logger.error(f"KPI Calc: Fehler bei Performance-Berechnung: {e}")
    
    # Renditen für Risiko-KPIs
    try:
        if not pd.api.types.is_numeric_dtype(df["close"]):
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df.dropna(subset=["close"], inplace=True)
            if len(df) < 2: return kennzahlen

        renditen = df["close"].pct_change().dropna()

        if len(renditen) >= 1:
            kennzahlen["varianz_d"] = renditen.var()
            kennzahlen["std_abw_d"] = renditen.std()
            
            # +++ NEU: Annualisierte Volatilität +++
            trading_days = 252
            if pd.notna(kennzahlen["std_abw_d"]):
                kennzahlen["vola_a"] = kennzahlen["std_abw_d"] * np.sqrt(trading_days)

            downside_renditen = renditen[renditen < 0]
            kennzahlen["downside_risk_d"] = downside_renditen.std() if not downside_renditen.empty else 0.0
            
            if len(renditen) >= 20: # Braucht etwas mehr Daten für stabile Quantile
                kennzahlen["var95_d"] = renditen.quantile(0.05)

            if pd.notna(jahre) and jahre > 0: # Für annualisierte Ratios
                mean_return_d = renditen.mean()
                std_abw_d_val = kennzahlen["std_abw_d"]
                downside_risk_d_val = kennzahlen["downside_risk_d"]

                if pd.notna(std_abw_d_val) and std_abw_d_val > 1e-9:
                    kennzahlen["sharpe_a"] = (mean_return_d * trading_days) / (std_abw_d_val * np.sqrt(trading_days))
                
                if pd.notna(downside_risk_d_val) and downside_risk_d_val > 1e-9:
                    kennzahlen["sortino_a"] = (mean_return_d * trading_days) / (downside_risk_d_val * np.sqrt(trading_days))
            
            # +++ NEU: Max Drawdown +++
            # Max Drawdown auf Basis der 'close' Spalte (Kurse oder Indexwerte)
            # Wenn 'close' schon ein Index ist (z.B. Start 100), ist das Ergebnis direkt der prozentuale Drawdown / 100
            cumulative_max = df['close'].cummax()
            drawdown = (df['close'] - cumulative_max) / cumulative_max 
            # Ersetze -inf (wenn cummax 0 war und close auch 0), bevor min gesucht wird
            drawdown.replace([np.inf, -np.inf], np.nan, inplace=True) 
            max_drawdown_value = drawdown.min()
            kennzahlen['max_drawdown'] = max_drawdown_value if pd.notna(max_drawdown_value) else np.nan

    except Exception as e: logger.error(f"KPI Calc: Fehler bei Risiko-Berechnung: {e}", exc_info=True)
    
    logger.info(f"KPI Calc: Berechnung abgeschlossen für Daten von {kennzahlen['start_datum']} bis {kennzahlen['end_datum']}.")
    return kennzahlen
