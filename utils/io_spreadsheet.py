"""
Utility functions for reading and writing spreadsheet files and coercing numeric
columns.

This module abstracts away the differences between various spreadsheet formats
commonly used in the project (Excel, OpenDocument Spreadsheets and CSV). It
provides convenience helpers to read and write pandas ``DataFrame`` objects
without worrying about which underlying engine is required. Additionally, it
contains a helper to normalise numeric data stored as text (often with
whitespace or comma separators) into proper numeric types.  These helpers are
used throughout the import and report handlers to ensure consistent data handling.

Functions
---------

read_any_spreadsheet(path: str) -> pandas.DataFrame
    Read an input file into a ``pandas.DataFrame`` based on its extension.

write_any_spreadsheet(df: pandas.DataFrame, path: str) -> None
    Write a ``pandas.DataFrame`` to disk using a format inferred from the
    filename extension.

coerce_numeric_columns(df: pandas.DataFrame, columns: Optional[Iterable[str]] = None)
    Coerce specified columns (or all object‑dtype columns by default) to
    numeric. Cleans whitespace and replaces commas with dots before
    conversion.

write_table(df: pandas.DataFrame, path: str, fmt: str = "xlsx", sheet_name: str = "Sheet1", index: bool = False) -> None
    Write a ``DataFrame`` to disk using the specified format. Supports Excel,
    OpenDocument Spreadsheet and CSV formats. The format is chosen by the
    ``fmt`` argument rather than the file extension of ``path``.
"""

from __future__ import annotations

from typing import Iterable, Optional

import pandas as pd


def read_any_spreadsheet(path: str) -> pd.DataFrame:
    """Read a spreadsheet file of various supported formats into a DataFrame.

    Supported extensions include Excel (.xlsx, .xlsm), OpenDocument Spreadsheet
    (.ods) and Comma Separated Values (.csv). The correct pandas reader is
    chosen based on the file suffix. For Excel and ODS files the appropriate
    engine is selected automatically; if an engine is missing (e.g. ``odfpy``
    for .ods files) a ``RuntimeError`` is raised.

    Parameters
    ----------
    path : str
        Path to the spreadsheet file to read.

    Returns
    -------
    pd.DataFrame
        A DataFrame containing the data from the spreadsheet.

    Raises
    ------
    ValueError
        If the file extension is not recognised.
    RuntimeError
        If a required engine for reading the file type is not available.
    """
    lower = path.lower()
    if lower.endswith(('.xlsx', '.xlsm')):
        # Excel formats using openpyxl engine
        return pd.read_excel(path, engine='openpyxl')
    if lower.endswith('.ods'):
        # OpenDocument Spreadsheet requires odfpy
        try:
            return pd.read_excel(path, engine='odf')
        except ImportError as exc:
            raise RuntimeError(
                "Reading .ods files requires the optional dependency 'odfpy'."
            ) from exc
    if lower.endswith('.csv'):
        return pd.read_csv(path)
    raise ValueError(f"Unsupported file extension: {path}")


def write_any_spreadsheet(df: pd.DataFrame, path: str) -> None:
    """Write a DataFrame to a spreadsheet file inferred by its extension.

    The output format is determined by the extension of ``path``. Excel
    (.xlsx, .xlsm), OpenDocument Spreadsheet (.ods) and CSV (.csv) formats are
    supported. The appropriate writer engine is selected automatically; for
    writing .ods files a RuntimeError is raised if ``odfpy`` is not installed.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to write to disk.
    path : str
        Destination file path. The suffix determines the file format.

    Raises
    ------
    ValueError
        If the extension is not recognised.
    RuntimeError
        If the engine required for writing the file type is not available.
    """
    lower = path.lower()
    if lower.endswith(('.xlsx', '.xlsm')):
        df.to_excel(path, index=False, engine='openpyxl')
        return
    if lower.endswith('.ods'):
        try:
            df.to_excel(path, index=False, engine='odf')
        except ImportError as exc:
            raise RuntimeError(
                "Writing .ods files requires the optional dependency 'odfpy'."
            ) from exc
        return
    if lower.endswith('.csv'):
        df.to_csv(path, index=False)
        return
    raise ValueError(f"Unsupported file extension: {path}")


def coerce_numeric_columns(df: pd.DataFrame, columns: Optional[Iterable[str]] = None) -> pd.DataFrame:
    """Convert textual numeric columns into numeric dtype within a DataFrame.

    This helper attempts to parse columns containing numbers represented as
    strings (possibly with whitespace or comma decimal separators) into proper
    numeric types. If ``columns`` is None, all columns with object dtype are
    considered candidates for conversion. Entries that cannot be parsed remain
    unchanged. The DataFrame is modified in place and also returned for
    convenience.

    Parameters
    ----------
    df : pd.DataFrame
        The DataFrame whose columns should be coerced.
    columns : Iterable[str], optional
        Specific columns to attempt conversion on. If omitted, all columns
        with dtype ``object`` are used.

    Returns
    -------
    pd.DataFrame
        The same DataFrame with selected columns coerced to numeric where
        possible.
    """
    if columns is None:
        target_cols = [col for col in df.columns if df[col].dtype == object]
    else:
        target_cols = list(columns)

    for col in target_cols:
        # Skip non‑existent columns gracefully
        if col not in df.columns:
            continue
        series = df[col]
        # Only process object-like columns to avoid unintended conversions
        if not pd.api.types.is_object_dtype(series):
            continue
        # Convert values to strings, remove whitespace and replace comma with dot
        cleaned = (
            series.astype(str)
            .str.strip()
            .str.replace(r"\s+", "", regex=True)
            .str.replace(",", ".")
        )
        # Replace empty strings with NaN to allow numeric conversion
        cleaned = cleaned.replace({"": pd.NA})
        # Try to convert to numeric; invalid parsing will stay as string
        df[col] = pd.to_numeric(cleaned, errors='ignore')
    return df


def write_table(
    df: pd.DataFrame,
    path: str,
    fmt: str = "xlsx",
    sheet_name: str = "Sheet1",
    index: bool = False,
) -> None:
    """Write a DataFrame to disk in the specified spreadsheet format.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to write.
    path : str
        Base path or file name where the table should be saved. The file extension
        is ignored; the format is determined by the ``fmt`` argument.
    fmt : str, optional
        Format to use for output ('xlsx', 'ods' or 'csv'). Default is 'xlsx'.
    sheet_name : str, optional
        Name of the sheet when saving to Excel or ODS formats.
    index : bool, optional
        Whether to write DataFrame index into the file. Defaults to False.

    Raises
    ------
    ValueError
        If the provided format is not supported.
    RuntimeError
        If writing ODS files is requested but the required engine is not installed.
    """
    ext = fmt.lower().lstrip(".")
    # Accept both xlsx and xlsm as Excel formats
    if ext not in ("xlsx", "xlsm", "ods", "csv"):
        raise ValueError(f"Unsupported format: {fmt}")
    # Determine full output path with correct suffix
    from pathlib import Path
    output_path = Path(path).with_suffix(f".{ext}")
    # Excel formats
    if ext in ("xlsx", "xlsm"):
        df.to_excel(output_path, index=index, engine='openpyxl', sheet_name=sheet_name)
        return
    # OpenDocument Spreadsheet
    if ext == "ods":
        try:
            df.to_excel(output_path, index=index, engine='odf', sheet_name=sheet_name)
        except ImportError as exc:
            raise RuntimeError(
                "Writing .ods files requires the optional dependency 'odfpy'."
            ) from exc
        return
    # CSV
    df.to_csv(output_path, index=index)
    return