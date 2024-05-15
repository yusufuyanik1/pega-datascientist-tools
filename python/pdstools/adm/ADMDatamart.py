from __future__ import annotations

import logging
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Literal, NoReturn, Optional, Tuple, Union
from collections import namedtuple

import polars as pl
import yaml
import glob

from ..plots.plot_base import Plots
from ..plots.plots_plotly import ADMVisualisations as plotly_plot
from ..utils import cdh_utils
from ..utils.errors import NotEagerError
from ..utils.types import any_frame
from .. import pega_io
from .ADMTrees import ADMTrees
from .Tables import Tables


class ADMDatamart(Plots, Tables):
    """Main class for importing, preprocessing and structuring Pega ADM Datamart.
    Gets all available data, properly names and merges into one main dataframe.

    It's also possible to import directly from S3. Please refer to
    :meth:`pdstools.pega_io.S3.S3Data.get_ADMDatamart`.

    Parameters
    ----------
    path : str, default = "."
        The path of the data files
    import_strategy: Literal['eager', 'lazy'], default = 'eager'
        Whether to import the file fully to memory, or scan the file
        When data fits into memory, 'eager' is typically more efficient
        However, when data does not fit, the lazy methods typically allow
        you to still use the data.

    Keyword arguments
    -----------------
    model_filename : Optional[str]
        The name, or extended filepath, towards the model file
    predictor_filename : Optional[str]
        The name, or extended filepath, towards the predictors file
    model_df : Union[pl.DataFrame, pl.LazyFrame, pd.DataFrame]
        Optional override to supply a dataframe instead of a file
    predictor_df : Union[pl.DataFrame, pl.LazyFrame, pd.DataFrame]
        Optional override to supply a dataframe instead of a file
    query : Union[pl.Expr, str, Dict[str, list]], default = None
        Please refer to :meth:`._apply_query`
    plotting_engine : str, default = "plotly"
        Please refer to :meth:`.get_engine`
    subset : bool, default = True
        Whether to only keep a subset of columns for efficiency purposes
        Refer to :meth:`._available_columns` for the default list of columns.
    drop_cols : Optional[list]
        Columns to exclude from reading
    include_cols : Optional[list]
        Additionial columns to include when reading
    context_keys : list, default = ["Channel", "Direction", "Issue", "Group"]
        Which columns to use as context keys
    extract_keys : bool, default = False
        Extra keys, particularly pyTreatment, are hidden within the pyName column.
        extract_keys can expand that cell to also show these values.
        To extract these extra keys, set extract_keys to True.
    verbose : bool, default = False
        Whether to print out information during importing
    **reading_opts
        Additional parameters used while reading.
        Refer to :meth:`pdstools.pega_io.File.import_file` for more info.

    Attributes
    ----------
    modelData : pl.LazyFrame
        If available, holds the preprocessed data about the models
    predictorData : pl.LazyFrame
        If available, holds the preprocessed data about the predictor binning
    combinedData : pl.LazyFrame
        If both modelData and predictorData are available,
        holds the merged data about the models and predictors
    import_strategy
        See the `import_strategy` parameter
    query
        See the `query` parameter
    context_keys
        See the `context_keys` parameter
    verbose
        See the `verbose` parameter


    Examples
    --------
    >>> Data =  ADMDatamart("/CDHSample")
    >>> Data =  ADMDatamart("Data/Adaptive Models & Predictors Export",
                model_filename = "Data-Decision-ADM-ModelSnapshot_AdaptiveModelSnapshotRepo20201110T085543_GMT/data.json",
                predictor_filename = "Data-Decision-ADM-PredictorBinningSnapshot_PredictorBinningSnapshotRepo20201110T084825_GMT/data.json")
    >>> Data =  ADMDatamart("Data/files",
                model_filename = "ModelData.csv",
                predictor_filename = "PredictorData.csv")

    """

    standardChannelGroups = [
        "Web",
        "Mobile",
        "E-mail",
        "Push",
        "SMS",
        "Retail",
        "Call Center",
        "IVR",
    ]
    standardDirections = ["Inbound", "Outbound"]

    NBAD_configurations = namedtuple(
        "Configurations",
        ["model_name", "channel", "direction", "standard", "multi_channel"],
    )
    standardNBADModelConfigurationList: List[NBAD_configurations] = [
        ("Web_Click_Through_Rate", "Web", "Inbound", True, False),
        ("WebTreatmentClickModel", "Web", "Inbound", True, False),
        ("Mobile_Click_Through_Rate", "Mobile", "Inbound", True, False),
        ("Email_Click_Through_Rate", "E-mail", "Outbound", True, False),
        ("Push_Click_Through_Rate", "Push", "Outbound", True, False),
        ("SMS_Click_Through_Rate", "SMS", "Outbound", True, False),
        ("Retail_Click_Through_Rate", "Retail", "Inbound", True, False),
        ("Retail_Click_Through_Rate_Outbound", "Retail", "Outbound", True, False),
        ("CallCenter_Click_Through_Rate", "Call Center", "Inbound", True, False),
        ("CallCenterAcceptRateOutbound", "Call Center", "Outbound", True, False),
        (
            "Assisted_Click_Through_Rate",
            "Assisted",
            "Inbound",
            True,
            False,
        ),  # withdrawn record
        (
            "Assisted_Click_Through_Rate_Outbound",
            "Assisted",
            "Outbound",
            True,
            False,
        ),  # withdrawn record
        ("Default_Inbound_Model", "Default", "Inbound", True, False),
        ("Default_Outbound_Model", "Default", "Outbound", True, False),
        ("Default_Click_Through_Rate", "Other", "Inbound", True, False),
        ("Other_Inbound_Click_Through_Rate", "Other", "Inbound", True, False),
        ("OmniAdaptiveModel", "Multi-channel", "Multi-channel", True, True),
    ]

    NBAD_model_configurations = [
        x[0].upper() for x in standardNBADModelConfigurationList
    ]

    def __init__(
        self,
        path: Union[str, Path] = Path("."),
        import_strategy: Literal["eager", "lazy"] = "eager",
        *,
        model_filename: Optional[str] = "modelData",
        predictor_filename: Optional[str] = "predictorData",
        model_df: Optional[any_frame] = None,
        predictor_df: Optional[any_frame] = None,
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]] = None,
        subset: bool = True,
        drop_cols: Optional[list] = None,
        include_cols: Optional[list] = None,
        context_keys: list = [
            "Channel",
            "Direction",
            "Issue",
            "Group",
        ],  # TODO Name/Treatment are normally also part of context
        extract_keys: bool = False,  # TODO: should be True by default, extract should be efficiently using Configuration
        predictorCategorization: pl.Expr = cdh_utils.defaultPredictorCategorization,
        plotting_engine: Union[
            str, Any
        ] = "plotly",  # TODO drop this, no plot engine abstraction
        verbose: bool = False,
        **reading_opts,
    ):
        self.import_strategy = import_strategy
        self.context_keys = context_keys
        self.verbose = verbose
        self.query = query
        self.predictorCategorization = predictorCategorization

        self.modelData, self.predictorData = self.import_data(
            path,
            model_filename=model_filename,
            predictor_filename=predictor_filename,
            model_df=model_df,
            predictor_df=predictor_df,
            subset=subset,
            drop_cols=drop_cols,
            include_cols=include_cols,
            extract_keys=extract_keys,
            **reading_opts,
        )
        if self.modelData is not None:
            missing_context_keys = [
                key for key in self.context_keys if key not in self.modelData.columns
            ]
            if missing_context_keys:
                self.modelData = self.modelData.with_columns(
                    *[pl.lit("NA").alias(key) for key in missing_context_keys]
                )

        self.plotting_engine = plotting_engine
        super().__init__()

        self.processTables(self.query)

    # TODO: Lets drop the configurable plotting engines, but isolate the plotly code

    @staticmethod
    def get_engine(plotting_engine):
        """Which engine to use for creating the plots.

        By supplying a custom class here, you can re-use the pdstools functions
        but create visualisations to your own specifications, in any library.
        """
        if not isinstance(plotting_engine, str):
            return plotting_engine
        elif plotting_engine == "plotly":
            return plotly_plot
        else:
            msg = (
                f"Plotting engine {plotting_engine} not known. "
                "Please supply your own class with function names corresponding to plot_base.py "
                "or pass 'Plotly' to use the default engine."
            )
            raise ValueError(msg)

    def import_data(
        self,
        path: Optional[Union[str, Path]] = Path("."),
        *,
        model_filename: Optional[str] = "modelData",
        predictor_filename: Optional[str] = "predictorData",
        model_df: Optional[any_frame] = None,
        predictor_df: Optional[any_frame] = None,
        subset: bool = True,
        drop_cols: Optional[list] = None,
        include_cols: Optional[list] = None,
        extract_keys: bool = False,
        verbose: bool = False,
        **reading_opts,
    ) -> Tuple[Optional[pl.LazyFrame], Optional[pl.LazyFrame]]:
        """Method to import & format the relevant data.

        The method first imports the model data, and then the predictor data.
        If model_df or predictor_df is supplied, it will use those instead
        If any filters are included in the the `query` argument of the ADMDatmart,
        those will be applied to the modeldata, and the predictordata will be
        filtered such that it only contains the modelids leftover after filtering.
        After reading, some additional values (such as success rate) are
        automatically computed.
        Lastly, if there are missing columns from both datasets,
        this will be printed to the user if verbose is True.

        Parameters
        ----------
        path : Path
            The path of the data files
            Default = current path ('.')
        subset : bool, default = True
            Whether to only select the renamed columns,
            set to False to keep all columns
        model_df : pd.DataFrame
            Optional override to supply a dataframe instead of a file
        predictor_df : pd.DataFrame
            Optional override to supply a dataframe instead of a file
        drop_cols : Optional[list]
            Columns to exclude from reading
        include_cols : Optional[list]
            Additionial columns to include when reading
        extract_keys : bool, default = False
            Extra keys, particularly pyTreatment, are hidden within the pyName column.
            extract_keys can expand that cell to also show these values.
            To extract these extra keys, set extract_keys to True.
        verbose : bool, default = False
            Whether to print out information during importing

        Returns
        -------
        (polars.LazyFrame, polars.LazyFrame)
            The model data and predictor binning data as LazyFrames
        """

        if model_df is not None:
            df1, self.renamed_model, self.missing_model = self._import_utils(
                name=model_df,
                subset=subset,
                drop_cols=drop_cols,
                include_cols=include_cols,
                extract_keys=extract_keys,
                **reading_opts,
            )
        else:
            df1, self.renamed_model, self.missing_model = self._import_utils(
                name=model_filename,
                path=path,
                subset=subset,
                drop_cols=drop_cols,
                include_cols=include_cols,
                extract_keys=extract_keys,
                **reading_opts,
            )
        if df1 is not None:
            df1 = df1.with_columns(
                (pl.col("Positives") / pl.col("ResponseCount"))
                .fill_nan(pl.lit(0))
                .alias("SuccessRate"),
                self._last_timestamp("Positives"),
                self._last_timestamp("ResponseCount"),
            )
        if predictor_df is not None:
            df2, self.renamed_preds, self.missing_preds = self._import_utils(
                name=predictor_df,
                drop_cols=drop_cols,
                include_cols=include_cols,
                subset=subset,
                **reading_opts,
            )
        else:
            df2, self.renamed_preds, self.missing_preds = self._import_utils(
                name=predictor_filename,
                path=path,
                drop_cols=drop_cols,
                include_cols=include_cols,
                subset=subset,
                **reading_opts,
            )
        if df2 is not None:
            if "BinResponseCount" not in df2.columns:  # pragma: no cover
                df2 = df2.with_columns(
                    (pl.col("BinPositives") + pl.col("BinNegatigves")).alias(
                        "BinResponseCount"
                    )
                )
            df2 = df2.with_columns(
                BinPropensity=pl.col("BinPositives") / pl.col("BinResponseCount"),
                BinAdjustedPropensity=(
                    (pl.col("BinPositives") + pl.lit(0.5))
                    / (pl.col("BinResponseCount") + pl.lit(1))
                ),
            )

            if (
                self.predictorCategorization is not None
                and "PredictorCategory" not in df2.columns
            ):
                if not isinstance(self.predictorCategorization, pl.Expr):
                    self.predictorCategorization = self.predictorCategorization()
                df2 = df2.with_columns(PredictorCategory=self.predictorCategorization)

        if df1 is not None and df2 is not None:
            total_missing = (
                set(self.missing_model)
                & set(self.missing_preds) - set(df1.columns) - set(df2.columns)
            ) - {"Treatment"}
            if len(total_missing) > 0 and verbose:  # pragma: no cover
                print(
                    "Missing expected field values.\n",
                    "Please check if they are available in the data,\n",
                    "and supply a custom mapping if the naming is different from default.\n",
                    f"Missing values: {total_missing}",
                )

        return df1, df2

    @property
    def is_available(self) -> bool:
        return len(self.modelData.head(1).collect()) > 0

    def _import_utils(
        self,
        name: Union[str, any_frame],
        path: Optional[str] = None,
        *,
        subset: bool = True,
        extract_keys: bool = False,
        drop_cols: Optional[list] = None,
        include_cols: Optional[list] = None,
        **reading_opts,
    ) -> Tuple[pl.LazyFrame, dict, dict]:
        """Handler function to interface to the cdh_utils methods

        Parameters
        ----------
        name : Union[str, pl.DataFrame]
            One of {modelData, predictorData}
            or a dataframe
        path: str, default = None
            The path of the data file


        Keyword arguments
        -----------------
        subset : bool, default = True
            Whether to only select the renamed columns,
            set to False to keep all columns
        drop_cols : list
            Supply columns to drop from the dataframe
        include_cols : list
            Supply columns to include with the dataframe
        extract_keys : bool
            Treatments are typically hidden within the pyName column,
            extract_keys can expand that cell to also show these values.

        Additional keyword arguments
        ----------------------------
        See :meth:`pdstools.pega_io.File.readDSExport`

        Returns
        -------
        (pl.LazyFrame, dict, dict)
            - The requested dataframe,
            - The renamed columns
            - The columns missing in both dataframes)
        """

        if isinstance(name, BytesIO):
            self.import_strategy = "eager"

        if isinstance(name, str) or isinstance(name, BytesIO):
            df = pega_io.readDSExport(
                filename=name, path=path, verbose=self.verbose, **reading_opts
            )
        elif isinstance(name, pl.DataFrame):
            df = name.lazy()
            self.import_strategy = "eager"

        elif isinstance(name, pl.LazyFrame):
            df = name.lazy()

        else:
            return None, None, None
        if df is None:
            return None, None, None

        df = cdh_utils._polarsCapitalize(df)
        cols, missing = self._available_columns(
            df, include_cols=include_cols, drop_cols=drop_cols
        )
        if subset:
            df = df.select(cols)
        if extract_keys:
            df = cdh_utils._extract_keys(df, import_strategy=self.import_strategy)
            df = cdh_utils._polarsCapitalize(df)

        df = self._set_types(
            df,
            timestamp_fmt=reading_opts.get("timestamp_fmt", None),
            strict_conversion=reading_opts.get("strict_conversion", True),
            table=reading_opts.get("typesetting_table", "infer"),
        )

        if self.query is not None:
            try:
                df = self._apply_query(df, self.query)
                if self.verbose:
                    print(f"Query successful for {name}.")
            except pl.ColumnNotFoundError:
                if self.verbose:
                    print(
                        f"""Query unsuccessful for {name}.
                Maybe the filter you selected only applies to either model data or predictor data
                and thus can't be successful for the other one. That should be fine
                as the other table is likely queried correctly."""
                    )
        return df, cols, missing

    def _available_columns(
        self,
        df: pl.LazyFrame,
        include_cols: Optional[list] = None,
        drop_cols: Optional[list] = None,
    ) -> Tuple[set, set]:
        """Based on the default names for variables, rename available data to proper formatting

        Parameters
        ----------
        df : pl.LazyFrame
            Input dataframe
        include_cols : list
            Supply columns to include with the dataframe
        drop_cols : list
            Supply columns to not import at all

        Returns
        -------
        Tuple[set, set]
            The original dataframe, but renamed for the found columns &
            The original and updated names for all renamed columns &
            The variables that were not found in the table
        """
        default_names = {
            "ModelID",
            "Issue",
            "Group",
            "Channel",
            "Direction",
            "Name",
            "Treatment",
            "Positives",
            "Configuration",
            "ResponseCount",
            "SnapshotTime",
            "PredictorName",
            "PredictorCategory",
            "Performance",
            "EntryType",
            "PredictorName",
            "BinSymbol",
            "BinIndex",
            "BinType",
            "BinPositives",
            "BinNegatives",
            "BinResponseCount",
            "Type",
            "Contents",
            "GroupIndex",
        }  # NOTE: these default names are already capitalized properly, with py/px/pz removed.

        rename = {i: "Name" for i in df.columns if i.lower() == "modelname"}
        if len(rename) > 0:
            df = df.rename(rename)

        include_cols = (
            set(cdh_utils._capitalize(include_cols)) if include_cols is not None else {}
        )
        drop_cols = (
            set(cdh_utils._capitalize(drop_cols)) if drop_cols is not None else {}
        )

        include_cols = default_names.union(include_cols).difference(drop_cols)
        missing = {col for col in include_cols if col not in df.columns}
        to_import = include_cols.intersection(set(df.columns))

        return to_import, missing

    def _set_types(
        self,
        df: any_frame,
        table: str = "infer",
        *,
        timestamp_fmt: str = None,
        strict_conversion: bool = True,
    ) -> any_frame:
        """A method to change columns to their proper type

        Parameters
        ----------
        df : Union[pl.DataFrame, pl.LazyFrame]
            The input dataframe
        table: str
            The table to set types for. Default is infer, in which case
            it infers the table type from the columns in it.

        Keyword arguments
        -----------------
        timestamp_fmt: str
            The format of Date type columns
        strict_conversion: bool
            Raises an error if timestamp conversion to given/default date format(timestamp_fmt) fails
            See 'https://strftime.org/' for timestamp formats
        Returns
        -------
        Union[pl.DataFrame, pl.LazyFrame]
            The input dataframe, but the proper typing applied
        """

        df = cdh_utils.set_types(
            df,
            table,
            verbose=self.verbose,
            timestamp_fmt=timestamp_fmt,
            strict_conversion=strict_conversion,
        )
        if "SnapshotTime" not in df.columns:
            df = df.with_columns(SnapshotTime=None)
        return df

    def last(
        self, table="modelData", strategy: Literal["eager", "lazy"] = "eager"
    ) -> any_frame:
        """Convenience function to get the last values for a table

        Parameters
        ----------
        table : str, default = modelData
            Which table to get the last values for
            One of {modelData, predictorData, combinedData}
        strategy: Literal['eager', 'lazy'], default = 'eager'
            Whether to import the file fully to memory, or scan the file
            When data fits into memory, 'eager' is typically more efficient
            However, when data does not fit, the lazy methods typically allow
            you to still use the data.

        Returns
        -------
        Union[pl.DataFrame, pl.LazyFrame]
            The last snapshot for each model
        """

        if isinstance(table, pl.LazyFrame):
            df = self._last(table)

        elif isinstance(table, str):
            assert table in {"modelData", "predictorData", "combinedData"}
            df = self._last(getattr(self, table))
        else:  # pragma: no cover
            raise ValueError("This should not happen, please file a GitHub issue :).")
        return df if not strategy == "eager" else df.collect()

    @staticmethod
    def _last(df: any_frame) -> any_frame:
        """Method to retrieve only the last snapshot."""
        return df.filter(
            pl.col("SnapshotTime").fill_null(1)
            == pl.col("SnapshotTime").fill_null(1).max()
        )

    @staticmethod
    def _last_timestamp(col: Literal["ResponseCount", "Positives"]) -> pl.Expr:
        """Add a column to indicate the last timestamp a column has changed.

        Parameters
        ----------
        col : Literal['ResponseCount', 'Positives']
            The column to calculate the diff for
        """

        return (
            pl.when(pl.col(col).min() == pl.col(col).max())
            .then(pl.max("SnapshotTime"))
            .otherwise(pl.col("SnapshotTime").filter(pl.col(col).diff() != 0).max())
            .over("ModelID")
            .alias(f"Last_{col}")
        )

    def _get_combined_data(
        self, last=True, strategy: Literal["eager", "lazy"] = "eager"
    ) -> any_frame:
        """Combines the model data and predictor data into one dataframe.

        Parameters
        ----------
        last:bool, default=True
            Whether to only use the last snapshot for each table
        strategy: Literal['eager', 'lazy'], default = 'eager'
            Whether to import the file fully to memory, or scan the file
            When data fits into memory, 'eager' is typically more efficient
            However, when data does not fit, the lazy methods typically allow
            you to still use the data.

        Returns
        -------
        Union[pl.DataFrame, pl.LazyFrame]
            The combined dataframe
        """
        models = self.last(self.modelData, "lazy") if last else self.modelData
        preds = self.last(self.predictorData, "lazy") if last else self.predictorData
        combined = models.join(preds, on="ModelID", how="inner", suffix="Bin")
        if strategy == "eager":
            return combined.collect().lazy()
        else:
            return combined

    def processTables(
        self,
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]] = None,
    ) -> ADMDatamart:
        """Processes modelData, predictorData and combinedData tables.

        Can take in a query, which it will apply to modelData
        If a query is given, it joins predictorData to only retain the modelIDs
        the modelData was filtered on. If both modelData and predictorData
        are present, it joins them together into combinedData.

        If memory_strategy is eager, which is the default, this method also
        collects the tables and then sets them back to lazy.

        Parameters
        ----------
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]], default = None
            An optional query to apply to the modelData table.
            See: :meth:`._apply_query`

        """
        if self.modelData is not None:
            if query is not None:
                self.modelData = self._apply_query(self.modelData, query)
            if self.import_strategy == "eager":
                self.modelData = self.modelData.collect().lazy()

        if self.predictorData is not None:
            if query is not None:
                self.predictorData = self.predictorData.join(
                    self.modelData.select(pl.col("ModelID").unique()), on="ModelID"
                )
            if self.import_strategy == "eager":
                self.predictorData = self.predictorData.collect().lazy()

        if self.predictorData is not None and self.modelData is not None:
            self.combinedData = self._get_combined_data(strategy=self.import_strategy)
        elif self.verbose:
            print(
                "Could not be combined. Do you have both model data and predictor data?"
            )

        return self

    def save_data(self, path: str = ".") -> Tuple[os.PathLike, os.PathLike]:
        """Cache modelData and predictorData to files.

        Parameters
        ----------
        path : str
            Where to place the files

        Returns
        -------
        (os.PathLike, os.PathLike):
            The paths to the model and predictor data files
        """
        from datetime import datetime

        time = datetime.now().strftime("%Y%m%dT%H%M%S.%f")[:-3]
        if self.modelData is not None:
            modeldata_cache = pega_io.cache_to_file(
                self.modelData, path, name=f"cached_modelData_{time}"
            )
        if self.predictorData is not None:
            predictordata_cache = pega_io.cache_to_file(
                self.predictorData, path, name=f"cached_predictorData_{time}"
            )
        else:
            predictordata_cache = None
        return modeldata_cache, predictordata_cache

    def _apply_query(
        self,
        df: any_frame,
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]] = None,
    ) -> pl.LazyFrame:
        """Given an input Polars dataframe, it filters the dataframe based on input query

        Parameters
        ----------
        df : Union[pl.DataFrame, pl.LazyFrame]
            The input dataframe
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]]
            If a Polars Expression, passes the expression into Polars' filter function.
            If a list of Polars Expressions, applies each of the expressions as filters.
            If a string, uses the Pandas query function (works only in eager mode,
            not recommended).
            Else, a dict of lists where the key is column name in the dataframe
            and the corresponding value is a list of values to keep in the dataframe
        Returns
        -------
        pl.DataFrame
            Filtered Polars DataFrame
        """
        if isinstance(df, pl.DataFrame):
            df = df.lazy()
        if query is not None:
            if isinstance(query, pl.Expr):
                col_diff = set(query.meta.root_names()) - set(df.columns)
                if len(col_diff) == 0:
                    return df.filter(query)

                else:
                    raise pl.ColumnNotFoundError(col_diff)

            if isinstance(query, list):
                for item in query:
                    if isinstance(item, pl.Expr):
                        col_diff = set(item.meta.root_names()) - set(df.columns)
                        if len(col_diff) == 0:
                            df = df.filter(item)
                        else:
                            raise pl.ColumnNotFoundError(col_diff)
                    else:
                        raise ValueError(item)
                return df

            if isinstance(query, str):
                print(
                    "Pandas query detected. This will be slow, and only works in eager mode ",
                    "because we turn the dataframe to pandas, query, and then turn it back ",
                    "to Polars. For faster performance, please pass a Polars Expression ",
                    "which can be used in the `filter()` method.",
                )
                if not self.import_strategy == "eager":
                    raise NotEagerError("Applying pandas queries")
                else:
                    return pl.LazyFrame(
                        df.collect()
                        .to_pandas(use_pyarrow_extension_array=True)
                        .query(query)
                    )

            if not isinstance(query, dict):
                raise TypeError("query must be a dict where values are lists")
            for val in query.values():
                if not type(val) == list:
                    raise ValueError("query values must be list")

            for col, val in query.items():
                df = df.filter(pl.col(col).is_in(val))
        return df

    def discover_modelTypes(
        self, df: pl.LazyFrame, by: str = "Configuration", allow_collect=False
    ) -> Dict:  # pragma: no cover
        """Discovers the type of model embedded in the pyModelData column.

        By default, we do a group_by Configuration, because a model rule can only
        contain one type of model. Then, for each configuration, we look into the
        pyModelData blob and find the _serialClass, returning it in a dict.

        Parameters
        ----------
        df: pl.LazyFrame
            The dataframe to search for model types
        by: str
            The column to look for types in. Configuration is recommended.
        allow_collect: bool, default = False
            Set to True to allow discovering modelTypes, even if in lazy strategy.
            It will fetch one modelData string per configuration.
        """
        if self.import_strategy != "eager" and allow_collect == False:
            raise NotEagerError("Discovering AGB models")
        if "Modeldata" not in df.columns:
            raise ValueError(
                (
                    "Modeldata column not in the data. "
                    "Please make sure to include it by using the 'include_cols' "
                    "argument with your ADMDatamart call, or setting 'subset' to False."
                )
            )

        def _getType(val):
            import base64
            import zlib

            return next(
                line.split('"')[-2].split(".")[-1]
                for line in zlib.decompress(base64.b64decode(val)).decode().split("\n")
                if line.startswith('  "_serialClass"')
            )

        if isinstance(df, pl.DataFrame):
            df = df.lazy()

        types = (
            df.filter(pl.col("Modeldata").is_not_null())
            .group_by(by)
            .agg(pl.col("Modeldata").last())
            .collect()
            .with_columns(pl.col("Modeldata").map_elements(lambda v: _getType(v)))
            .to_dicts()
        )
        return {key: value for key, value in [i.values() for i in types]}

    def get_AGB_models(
        self,
        last: bool = False,
        by: str = "Configuration",
        n_threads: int = 1,
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]] = None,
        verbose: bool = True,
        **kwargs,
    ) -> Dict:  # pragma: no cover
        """Method to automatically extract AGB models.

        Recommended to subset using the querying functionality
        to cut down on execution time, because it checks for each
        model ID. If you only have AGB models remaining after the query,
        it will only return proper AGB models.

        Parameters
        ----------
        last: bool, default = False
            Whether to only look at the last snapshot for each model
        by: str, default = 'Configuration'
            Which column to determine unique models with
        n_threads: int, default = 6
            The number of threads to use for extracting the models.
            Since we use multithreading, setting this to a reasonable value
            helps speed up the import.
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]]
            Please refer to :meth:`._apply_query`
        verbose: bool, default = False
            Whether to print out information while importing

        """
        df = self.modelData
        if query is not None:
            df = self._apply_query(df, query)

        modelTypes = self.discover_modelTypes(df)
        AGB_models = [
            model for model, type in modelTypes.items() if type.endswith("GbModel")
        ]
        logging.info(f"Found AGB models: {AGB_models}")
        df = df.filter(pl.col("Configuration").is_in(AGB_models))
        if df.select(pl.col("ModelID").n_unique()).collect().item() == 0:
            raise ValueError("No models found.")

        if last:
            return ADMTrees(
                self.last(df), n_threads=n_threads, verbose=verbose, **kwargs
            )
        else:
            return ADMTrees(
                df.select("Configuration", "SnapshotTime", "Modeldata").collect(),
                n_threads=n_threads,
                verbose=verbose,
                **kwargs,
            )

    @staticmethod
    def _create_sign_df(
        df: pl.LazyFrame,
        by: str = "Name",
        *,
        what: str = "ResponseCount",
        every: str = "1d",
        pivot: bool = True,
        mask: bool = True,
    ) -> pl.LazyFrame:
        """Generates dataframe to show whether responses decreased/increased from day to day

        For a given dataframe where columns are dates and rows are model names(by parameter),
        subtracts each day's value from the previous day's value per model. Then masks the data.
        If increased (desired situtation), it will put 1 in the cell, if no change, it will
        put 0, and if decreased it will put -1. This dataframe then could be used in the heatmap

        Parameters
        ----------
        df: pd.DataFrame
            This is typically pivoted ModelData
        by: str, default = Name
            Column to calculate the daily change for.

        Keyword arguments
        -----------------
        what: str, default = ResponseCount
            Column that contains response counts
        every: str, default = 1d
            Interval of the change window
        pivot: bool, default = True
            Returns a pivotted table with signs as value if set to true
        mask: bool, default = True
            Drops SnapshotTime and returns direction of change(sign).

        Returns
        -------
        pd.LazyFrame
            The dataframe with signs for increase or decrease in day to day
        """

        df = (
            df.with_columns(pl.col("SnapshotTime").cast(pl.Date))
            .sort("SnapshotTime")
            .with_columns(
                pl.col(what)
                .cast(pl.Int64)
                .diff()
                .alias("Daily_increase")
                .over("ModelID")
            )
            .group_by_dynamic("SnapshotTime", every=every, by=by)
            .agg(pl.sum("Daily_increase").alias("Increase"))
        )
        if pivot:
            df = (
                df.collect()
                .pivot(
                    index="SnapshotTime",
                    columns=by,
                    values="Increase",
                    aggregate_function="first",
                )
                .lazy()
            )
        if mask:
            df = df.with_columns((pl.all().exclude([by, "SnapshotTime"]).sign()))
        return df

    def model_summary(
        self,
        by: str = "ModelID",
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]] = None,
        **kwargs,
    ) -> pl.LazyFrame:
        """Convenience method to automatically generate a summary over models

        By default, it summarizes ResponseCount, Performance, SuccessRate & Positives by model ID.
        It also adds weighted means for Performance and SuccessRate,
        And adds the count of models without responses and the percentage.

        Parameters
        ----------
        by: str, default = ModelID
            By what column to summarize the models
        query: Optional[Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]]
            Please refer to :meth:`._apply_query`

        Returns
        -------
        pl.LazyFrame:
            group_by dataframe over all models
        """
        df = self._apply_query(self.modelData, query)
        data = self.last(df, strategy="lazy").lazy()

        aggcols = ["ResponseCount", "Performance", "SuccessRate", "Positives"]
        required_columns = set(aggcols).union({by})

        context_keys = kwargs.get("context_keys", self.context_keys)
        assert required_columns.issubset(set(data.columns) | set(context_keys))

        return (
            data.group_by(context_keys)
            .agg(
                [
                    pl.count(by).suffix("_count"),
                    pl.col([aggcols[0], aggcols[3]]).sum().suffix("_sum"),
                    pl.col(aggcols).max().suffix("_max"),
                    pl.col(aggcols).mean().suffix("_mean"),
                    (pl.col("ResponseCount") == 0)
                    .sum()
                    .alias("Count_without_responses"),
                    (
                        cdh_utils.weighted_performance_polars()
                        .alias("Performance_weighted")
                        .fill_nan(0.5)
                    ),
                    cdh_utils.weighted_average_polars("SuccessRate", "ResponseCount")
                    .fill_nan(0.0)
                    .alias("SuccessRate_weighted"),
                ],
            )
            .with_columns(
                (pl.col("Count_without_responses") / pl.col(f"{by}_count"))
                .alias("Percentage_without_responses")
                .fill_nan(0.0)
            )
        )

    def pivot_df(
        self,
        df: pl.LazyFrame,
        by: Union[str, list] = "Name",
        *,
        allow_collect: bool = True,
        top_n: int = 0,
    ) -> pl.DataFrame:
        """Simple function to extract pivoted information

        Parameters
        ----------
        df : pl.LazyFrame
            The input DataFrame.
        by : Union[str, list], default = Name
            The column(s) to pivot the DataFrame by.
            If a list is provided, only the first element is used.
        allow_collect : bool, default = True
            Whether to allow eager computation.
            If set to False and the import strategy is "lazy", an error will be raised.
        top_n : int, optional (default=0)
            The number of rows to include in the pivoted DataFrame.
            If set to 0, all rows are included.

        Returns
        -------
        pl.DataFrame
            The pivoted DataFrame.
        """

        if isinstance(by, list):
            by = by[0]
        if self.import_strategy == "lazy" and not allow_collect:
            raise NotEagerError("Pivot df.")

        df = df.filter(pl.col("PredictorName") != "Classifier").with_columns(
            pl.col("PerformanceBin").fill_nan(0.5),
        )
        if by not in ["ModelID", "Name"]:
            df = (
                df.unique(subset=[by] + ["PredictorName"], keep="first")
                .group_by([by, "PredictorName"])
                .agg(
                    cdh_utils.weighted_average_polars(
                        "PerformanceBin", "ResponseCountBin"
                    )
                )
            )
        df = (
            df.collect()
            .pivot(
                index=by,
                columns="PredictorName",
                values="PerformanceBin",
                aggregate_function="first",
            )
            .fill_null(0.5)
            .fill_nan(0.5)
        )
        mod_order = (
            df.select(
                pl.concat_list(pl.col(pl.Float64))
                .list.eval(pl.element().mean())
                .list.get(0)
            )
            .select(pl.all().arg_sort(descending=True))
            .to_series()
        )[:top_n]
        pred_order = [by] + [
            df.columns[i + 1]
            for i in 0
            + df.select(pl.col(pl.Float64).mean())
            .transpose()
            .select(pl.all().arg_sort(descending=True))
            .to_series()
        ][:top_n]

        return df[mod_order].select(pred_order)

    @staticmethod
    def response_gain_df(df: any_frame, by: str = "Channel") -> any_frame:
        """Simple function to extract the response gain per model"""
        if isinstance(by, list):
            by = by[0]
        return (
            df.group_by([by, "ModelID"])
            .agg(pl.max("ResponseCount"))
            .sort([by, "ResponseCount"], descending=True)
            .with_columns(
                [
                    (pl.cum_sum("ResponseCount") / pl.sum("ResponseCount"))
                    .over(by)
                    .alias("TotalResponseFraction"),
                    ((pl.col(by).cumcount() + 1) / pl.count("ResponseCount"))
                    .over(by)
                    .alias("TotalModelsFraction"),
                ]
            )
        )

    def models_by_positives_df(
        self, df: pl.LazyFrame, by: str = "Channel", allow_collect=True
    ) -> pl.LazyFrame:
        """
        Compute statistics on the dataframe by grouping it by a given column `by`
        and computing the count of unique ModelIDs and cumulative percentage of unique
        models for with regard to the number of positive answers.

        Parameters
        ----------
        df : pl.LazyFrame
            The input DataFrame
        by : str, default = Channel
            The column name to group the DataFrame by, by default "Channel"
        allow_collect : bool, default = True
            Whether to allow eager computation. If set to False and the import strategy is "lazy", an error will be raised.

        Returns
        -------
        pl.LazyFrame
           DataFrame with PositivesBin column and model count statistics
        """
        if self.import_strategy == "lazy" and not allow_collect:
            raise NotEagerError("Models by positive df.")

        modelsByPositives = df.select([by, "Positives", "ModelID"]).collect()
        return (
            modelsByPositives.join(
                modelsByPositives["Positives"].cut(
                    breaks=list(range(0, 210, 10)),
                    series=False,
                    category_label="PositivesBin",
                ),
                on="Positives",
                how="left",
            )
            .lazy()
            .group_by([by, "PositivesBin", "break_point"])
            .agg([pl.min("Positives"), pl.n_unique("ModelID").alias("ModelCount")])
            .with_columns(
                (pl.col("ModelCount") / (pl.sum("ModelCount").over(by))).alias(
                    "cumModels"
                )
            )
            .sort("break_point")
        )

    def get_model_stats(self, last: bool = True) -> dict:
        """Returns a dictionary containing various statistics for the model data.

        Parameters
        ----------
        last : bool
            Whether to compute statistics only on the last snapshot. Defaults to True.

        Returns
        -------
        Dict
            A dictionary containing the following keys:
            'models_n_snapshots': The number of distinct snapshot times in the data.
            'models_total': The total number of models in the data.
            'models_empty': The models with no responses.
            'models_nopositives': The models with responses but no positive responses.
            'models_isimmature': The models with less than 200 positive responses.
            'models_noperformance': The models with at least 200 positive responses but a performance of 50.
            'models_n_nonperforming': The total number of models that are not performing well.
            'models_missing_{key}': The number of models with missing values for each context key.
            'models_bottom_left': The models with a performance of 50 and a success rate of 0.
        """
        if self.modelData is None:
            raise ValueError("No model data to analyze.")

        data = self.last(self.modelData) if last else self.modelData

        ret = dict()
        ret["models_n_snapshots"] = data.select(pl.n_unique("SnapshotTime")).item()
        ret["models_total"] = len(data)
        ret["models_empty"] = data.filter(pl.col("ResponseCount") == 0)
        ret["models_nopositives"] = data.filter(
            (pl.col("ResponseCount") > 0) & (pl.col("Positives") == 0)
        )
        ret["models_isimmature"] = data.filter(pl.col("Positives").is_between(0, 200))
        ret["models_noperformance"] = data.filter(
            (pl.col("Positives") >= 200) & (pl.col("Performance") == 0.5)
        )
        ret["models_n_nonperforming"] = (
            len(ret["models_empty"])
            + len(ret["models_nopositives"])
            + len(ret["models_isimmature"])
            + len(ret["models_noperformance"])
        )
        for key in self.context_keys:
            ret[f"models_missing_{key}"] = data.filter(pl.col(key).is_null())
        ret["models_bottom_left"] = data.filter(
            (pl.col("Performance") == 0.5) & (pl.col("SuccessRate") == 0)
        )
        self.model_stats = ret
        return ret

    def describe_models(self, **kwargs) -> NoReturn:
        """Convenience method to quickly summarize the models"""
        if not hasattr(self, "model_stats"):
            self.get_model_stats(last=True)
        assert {"models_empty"}.issubset(self.model_stats.keys())
        show_all_missing = kwargs.get("show_all_missing", True)
        nmodels = self.model_stats.get("models_total")

        ret = ""
        ret += f"""From all {nmodels} models:
{len(self.model_stats['models_empty'])} ({round(len(self.model_stats['models_empty'])/nmodels*100,2)}%) models have never recieved a response.
{len(self.model_stats['models_nopositives'])} ({round(len(self.model_stats['models_nopositives'])/nmodels*100,2)}%) models have been used but never recieved a 'positive' response.
{len(self.model_stats['models_isimmature'])} ({round(len(self.model_stats['models_isimmature'])/nmodels*100,2)}%) models are still in an 'immature' phase of learning (Positives between 1 and 200).
{len(self.model_stats['models_noperformance'])} ({round(len(self.model_stats['models_noperformance'])/nmodels*100,2)}%) models have recieved over 200 responses but still show minimum performance.
Meaning in total, {self.model_stats['models_n_nonperforming']} ({round(self.model_stats['models_n_nonperforming']/nmodels*100)}%) models do not perform as well as they could be.\n\n"""

        for key in self.model_stats.keys():
            if not isinstance(self.model_stats[key], int):
                if len(self.model_stats[key]) > 0 or show_all_missing:
                    ret += f"{len(self.model_stats[key])} ({round(len(self.model_stats[key])/nmodels*100,2)}%) {' '.join(key.split('_'))} attribute.\n"

        return ret

    def applyGlobalQuery(
        self, query: Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]
    ) -> ADMDatamart:
        """Convenience method to further query the datamart

        It's possible to give this query to the initial `ADMDatamart` class
        directly, but this method is more explicit. Filters on the model data
        (query is put in a :meth:`polars.filter()` method), filters the predictorData
        on the ModelIDs remaining after the query, and recomputes combinedData.

        Only works with Polars expressions.

        Paramters
        ---------
        query: Union[pl.Expr, List[pl.Expr], str, Dict[str, list]]
            The query to apply, see :meth:`._apply_query`
        """
        return self.processTables(query)

    def fillMissing(self) -> ADMDatamart:
        """Convenience method to fill missing values

        - Fills categorical, string and null type columns with "NA"
        - Fills SuccessRate, Performance and ResponseCount columns with 0
        - When context keys have empty string values, replaces them
        with "NA" string
        """
        self.modelData = self.modelData.with_columns(
            pl.col(pl.Categorical).fill_null("NA"),
            pl.col(pl.Utf8).fill_null("NA"),
            pl.col(pl.Null).fill_null("NA"),
            pl.col("SuccessRate").fill_nan(0).fill_null(0),
            pl.col("Performance").fill_nan(0).fill_null(0),
            pl.col("ResponseCount").fill_null(0),
        ).with_columns(
            [
                pl.when((pl.col(key) == "") | (pl.col(key) == " "))
                .then(pl.lit("NA"))
                .otherwise(pl.col(key))
                .alias(key)
                for key in self.context_keys
            ]
        )
        return self.processTables()

    def summary_by_channel(
        self, custom_channels: Dict[str, str] = None, keep_lists: bool = False
    ):
        if not custom_channels:
            custom_channels = {}

        # Removes whitespace and capitalizes names for matching
        def name_normalizer(x):
            return pl.col(x).str.replace_all("[ \-_]", "").str.to_uppercase()

        directionMapping = pl.DataFrame(
            # Standard directions have a 1:1 mapping to channel groups
            {
                "Direction": self.standardDirections,
                "DirectionGroup": self.standardDirections,
            }
        ).with_columns(normalizedDirection=name_normalizer("Direction"))

        channelGroupMapping = (
            pl.concat(
                [
                    pl.DataFrame(
                        # Standard channels have a 1:1 mapping to channel groups
                        {
                            "Channel": self.standardChannelGroups,
                            "ChannelGroup": self.standardChannelGroups,
                        }
                    ),
                    pl.DataFrame(
                        # feels like a convoluted way to put a dict into a polars dataframe
                        # but that is just what this does in the end
                        {
                            "Channel": custom_channels.keys(),
                            "ChannelGroup": [
                                custom_channels[c] for c in custom_channels.keys()
                            ],
                        }
                    ),
                ],
                how="diagonal",
            )
            .with_columns(normalizedChannel=name_normalizer("Channel"))
            .unique()
            .sort(["ChannelGroup", "Channel"])
        )

        actionIdentifierExpr = pl.concat_str(["Issue", "Group", "Name"], separator="/")
        activeActionExpr = (pl.col("ResponseCount").sum() > 0).over(
            ["Issue", "Group", "Name"]
        )

        # all these expressions needed because not every customer has Treatments and
        # polars can't aggregate literals, so we have to be careful to pass on explicit
        # values when there are no treatments
        treatmentIdentifierExpr = (
            pl.concat_str(["Issue", "Group", "Name", "Treatment"], separator="/")
            if "Treatment" in self.modelData.columns
            else pl.lit("")
        )
        activeTreatmentExpr = (
            (
                (pl.col("ResponseCount").sum() > 0)
                & (pl.col("Treatment").is_not_null())
            ).over(["Issue", "Group", "Name", "Treatment"])
            if "Treatment" in self.modelData.columns
            else pl.lit(False)
        )
        uniqueTreatmentExpr = (
            treatmentIdentifierExpr.unique()
            if "Treatment" in self.modelData.columns
            else pl.lit([])
        )
        uniqueTreatmentCountExpr = (
            treatmentIdentifierExpr.n_unique()
            if "Treatment" in self.modelData.columns
            else pl.lit(0)
        )
        uniqueUsedTreatmentExpr = (
            treatmentIdentifierExpr.filter(pl.col("isUsedTreatment")).unique()
            if "Treatment" in self.modelData.columns
            else pl.lit([])
        )
        uniqueUsedTreatmentCountExpr = (
            treatmentIdentifierExpr.filter(pl.col("isUsedTreatment")).n_unique()
            if "Treatment" in self.modelData.columns
            else pl.lit(0)
        )

        return (
            self.modelData.with_columns(
                activeActionExpr.alias("isUsedAction"),
                activeTreatmentExpr.alias("isUsedTreatment"),
            )
            # .filter(
            #     pl.col("Configuration").cast(pl.Utf8).str.to_uppercase()
            #     # TODO maybe not here...
            #     != "OMNIADAPTIVEMODEL"
            # )
            # .with_columns(
            #     OriginalChannelDirection=pl.concat_str(
            #         ["Channel", "Direction"], separator="/"
            #     )
            # )
            .with_columns(
                normalizedChannel=name_normalizer("Channel"),
                normalizedDirection=name_normalizer("Direction"),
            )
            .join(
                channelGroupMapping.lazy(),
                on="normalizedChannel",
                how="left",
                # suffix="_standard",
            )
            .join(
                directionMapping.lazy(),
                on="normalizedDirection",
                how="left",
                # suffix="_standard",
            )
            .with_columns(
                ChannelDirectionGroup=pl.when(
                    pl.col("ChannelGroup").is_not_null()
                    & pl.col("DirectionGroup").is_not_null()
                )
                .then(pl.concat_str(["ChannelGroup", "DirectionGroup"], separator="/"))
                .otherwise(pl.lit("Other")),
            )
            .group_by(
                [
                    "Channel",
                    "Direction",
                    "ChannelDirectionGroup",
                ]
            )
            .agg(
                pl.col("SnapshotTime").min().cast(pl.Date).alias("DateRange Min"),
                pl.col("SnapshotTime").max().cast(pl.Date).alias("DateRange Max"),
                # pl.col("OriginalChannelDirection"),
                pl.col("Positives").sum(),
                pl.col("ResponseCount").sum(),
                (cdh_utils.weighted_performance_polars() * 100).alias("Performance"),
                pl.col("Configuration").cast(pl.Utf8),
                pl.col("Configuration")
                .cast(pl.Utf8)
                .str.to_uppercase()
                .is_in(self.NBAD_model_configurations)
                .alias("isNBADModelConfiguration"),
                actionIdentifierExpr.n_unique().alias("Total Number of Actions"),
                uniqueTreatmentCountExpr.alias("Total Number of Treatments"),
                # TODO use last update property instead
                (actionIdentifierExpr.filter(pl.col("isUsedAction")).n_unique()).alias(
                    "Used Actions"
                ),
                uniqueUsedTreatmentCountExpr.alias("Used Treatments"),
                # keep lists of unique values for aggregation over channels
                AllIssues=pl.col("Issue").unique(),
                AllGroups=pl.concat_str(["Issue", "Group"], separator="/").unique(),
                AllActions=actionIdentifierExpr.unique(),
                AllTreatments=uniqueTreatmentExpr,
                AllUsedActions=actionIdentifierExpr.filter(
                    pl.col("isUsedAction")
                ).unique(),
                AllUsedTreatments=uniqueUsedTreatmentExpr,
            )
            .with_columns(
                pl.when(pl.col("Used Actions").is_not_null())
                .then(pl.col("Used Actions"))
                .otherwise(pl.lit(0))
                .alias("Used Actions"),
                pl.when(pl.col("Used Treatments").is_not_null())
                .then(pl.col("Used Treatments"))
                .otherwise(pl.lit(0))
                .alias("Used Treatments"),
                ChannelDirection=pl.format(
                    "{}/{}",
                    pl.when(pl.col("Channel").is_not_null())
                    .then(pl.col("Channel"))
                    .otherwise(pl.lit("Empty")),
                    pl.when(pl.col("Direction").is_not_null())
                    .then(pl.col("Direction"))
                    .otherwise(pl.lit("Empty")),
                ),
                isValid=(pl.col("Positives") > 200) & (pl.col("ResponseCount") > 1000),
                Configuration=pl.col("Configuration")
                .list.unique()
                .list.sort()
                .list.join(", "),
                Issues=pl.col("AllIssues").list.len(),
                Groups=pl.col("AllGroups").list.len(),
                # TODO: NBAD detection is not entirely correct: if the only standard model is omniadaptive, we
                # miss it, because that one got filtered out early on
                usesNBAD=pl.col("isNBADModelConfiguration").list.any(),
                usesNBADOnly=pl.col("isNBADModelConfiguration").list.any()
                & pl.col("isNBADModelConfiguration").list.all(),
            )
            .with_columns(CTR=(pl.col("Positives")) / (pl.col("ResponseCount")))
            .drop(
                ["isNBADModelConfiguration"]
                + (
                    []
                    if keep_lists
                    else [
                        "AllIssues",
                        "AllGroups",
                        "AllActions",
                        "AllUsedActions",
                        "AllTreatments",
                        "AllUsedTreatments",
                    ]
                )
            )
            .sort(
                [
                    "ChannelDirectionGroup",
                ]
            )
        )

    def overall_summary(self, custom_channels: Dict[str, str] = None):
        totalTreatments = (
            pl.col("AllTreatments").list.explode().n_unique()
            if "Treatment" in self.modelData.columns
            else pl.lit(0)
        )
        totalUsedTreatments = (
            pl.col("AllUsedTreatments").list.explode().n_unique()
            if "Treatment" in self.modelData.columns
            else pl.lit(0)
        )

        # Re-calculating here because the use of NBAD in the channel
        # summary does not currently take into account the omni adaptive model
        usesNBAD = (
            self.modelData.select(
                pl.col("Configuration")
                .cast(pl.Utf8)
                .str.to_uppercase()
                .is_in(self.NBAD_model_configurations)
                .any()
            )
            .collect()
            .item()
        )

        usesNBADOnly = (
            self.modelData.select(
                pl.col("Configuration")
                .cast(pl.Utf8)
                .str.to_uppercase()
                .is_in(self.NBAD_model_configurations)
                .all()
            )
            .collect()
            .item()
        )

        return (
            self.summary_by_channel(custom_channels, keep_lists=True)
            .filter(pl.col("isValid"))
            .select(
                pl.col("DateRange Min").min(),
                pl.col("DateRange Max").max(),
                pl.len().alias("Number of Valid Channels"),
                cdh_utils.weighted_performance_polars().alias("Performance"),
                pl.col("Positives").sum(),
                pl.col("ResponseCount").sum(),
                pl.col("Performance")
                .filter((pl.col("Performance") == pl.col("Performance").min()))
                .first()
                .alias("Minimum Performance"),
                pl.col("ChannelDirection")
                .filter((pl.col("Performance") == pl.col("Performance").min()))
                .first()
                .alias("Channel with Minimum Performance"),
                pl.col("AllIssues").list.explode().n_unique().alias("Issues"),
                pl.col("AllGroups").list.explode().n_unique().alias("Groups"),
                pl.col("AllActions")
                .list.explode()
                .n_unique()
                .alias("Total Number of Actions"),
                totalTreatments.alias("Total Number of Treatments"),
                pl.col("AllUsedActions")
                .list.explode()
                .n_unique()
                .alias("Used Actions"),
                totalUsedTreatments.alias("Used Treatments"),
                usesNBAD=pl.lit(usesNBAD),
                usesNBADOnly=(pl.len() > 0) & pl.lit(usesNBAD and usesNBADOnly),
            )
            .with_columns(CTR=(pl.col("Positives")) / (pl.col("ResponseCount")))
        )

    def generateReport(
        self,
        name: Optional[str] = None,
        working_dir: Path = Path("."),
        *,
        modelid: Optional[str] = "",
        delete_temp_files: bool = True,
        output_type: str = "html",
        allow_collect: bool = True,
        cached_data: bool = False,
        predictordetails_activeonly: bool = False,
        **kwargs,
    ):
        """
        Generates a report based on the provided parameters. If modelid is provided, a model report will be generated.
        If not, an overall HealthCheck report will be generated.

        Parameters
        ----------
        name : Optional[str], default = None
            The name of the report.
        working_dir : Path, default = Path(".")
            The working directory. Cached files will be written here.
        *
        Keyword Arguments
        -----------------
        modelid : Optional[str], default = ""
            The model id,
        delete_temp_files : bool, default = True
            Whether to delete temporary files.
        output_type : str, default = "html"
            The type of the output file.
        allow_collect : bool, default = True
            Whether to allow collection of data.
        cached_data : bool, default = False
            Whether to use cached data.
        del_cache : bool, default = True
            Whether to delete cache.
        predictordetails_activeonly : bool, default = False
            Whether to only include active predictor details.
        **kwargs
            Additional keyword arguments.
        """

        # Define helper functions
        def _delete_temp_files(working_dir, del_log=False):
            extensions = [".yaml", ".qmd", ".ipynb", ".arrow"]
            for ext in extensions:
                for f in glob.glob(f"{working_dir}/*{ext}"):
                    try:
                        os.remove(f)
                    except:
                        pass
            if del_log:
                try:
                    os.remove(f"{working_dir}/log.txt")
                except:
                    pass

        def get_report_files(modelid):
            if modelid == "":
                return "HealthCheck.qmd", "HealthCheck"
            else:
                return "ModelReport.qmd", "ModelReport"

        def get_output_filename(name, report, modelid, output_type):
            if name is not None:
                name = name.replace(" ", "_")
            if report == "ModelReport":
                if modelid is not None:
                    if name is not None:
                        return f"{report}_{name}_{modelid}.{output_type}"
                    else:
                        return f"{report}_{modelid}.{output_type}"
                else:
                    raise ValueError("ModelID cannot be None for a ModelReport.")
            elif report == "HealthCheck":
                if name is not None:
                    return f"{report}_{name}.{output_type}"
                else:
                    return f"{report}.{output_type}"
            else:
                raise ValueError("Invalid report type.")

        def check_output_file(working_dir, output_filename, verbose, delete_temp_files):
            if not os.path.exists(working_dir / output_filename):
                msg = "Error when generating healthcheck."
                if not verbose and not kwargs.get("output_to_file", False):
                    msg += "Set 'verbose' to True to see the full output"
                if delete_temp_files:
                    _delete_temp_files(working_dir)
                raise ValueError(msg)

        def get_files(working_dir, cached_data):
            if not cached_data:
                return self.save_data(working_dir)
            else:
                modeldata_files = glob.glob(f"{working_dir}/cached_modelData*")
                predictordata_files = glob.glob(f"{working_dir}/cached_predictorData*")
                if modeldata_files:
                    modeldata_cache = modeldata_files[0]
                else:
                    raise FileNotFoundError("No cached model data found.")
                if predictordata_files:
                    predictordata_cache = predictordata_files[0]
                else:
                    predictordata_cache = None
                return modeldata_cache, predictordata_cache

        def get_params(modelid, predictordetails_activeonly):
            return {
                "kwargs": {
                    "subset": False,
                    "modelid": modelid,
                    "predictordetails_activeonly": predictordetails_activeonly,
                },
            }

        def run_bash_command(bashCommand, working_dir, **kwargs):
            if not kwargs.get("verbose", self.verbose):
                stdout, stderr = subprocess.DEVNULL, None
            else:
                print("Set verbose=False to hide output.")
                print("Running:", bashCommand)
                stdout, stderr = subprocess.PIPE, subprocess.STDOUT
            if kwargs.get("output_to_file", False):
                with open(f"{working_dir}/log.txt", "w") as outfile:
                    process = subprocess.Popen(
                        bashCommand.split(),
                        stdout=outfile,
                        stderr=stderr,
                        cwd=working_dir,
                    )
                    process.communicate()
            else:
                process = subprocess.Popen(
                    bashCommand.split(), stdout=stdout, stderr=stderr, cwd=working_dir
                )
                process.communicate()

        # Main function logic
        healthcheck_file, report = get_report_files(modelid)
        verbose = kwargs.get("verbose", self.verbose)

        if self.import_strategy == "lazy" and not allow_collect:
            raise NotEagerError(f"Generating {report}")
        if not os.path.exists(working_dir):
            os.mkdir(working_dir)

        from pdstools import __reports__

        shutil.copy(__reports__ / healthcheck_file, working_dir)
        output_filename = get_output_filename(name, report, modelid, output_type)
        files = get_files(working_dir, cached_data)
        params = get_params(modelid, predictordetails_activeonly)

        with open(f"{working_dir}/params.yaml", "w") as f:
            yaml.dump(params, f)

        bashCommand = f"quarto render {healthcheck_file} --to {output_type} --output {output_filename} --execute-params params.yaml"

        run_bash_command(bashCommand, working_dir, **kwargs)

        check_output_file(working_dir, output_filename, verbose, delete_temp_files)
        if delete_temp_files:
            _delete_temp_files(working_dir, files)

        return f"{working_dir}/{output_filename}"

    def exportTables(self, file: Path = "Tables.xlsx", predictorBinning=False):
        """Exports all tables from `pdstools.adm.Tables` into one Excel file.

        Parameters
        ----------
        file: Path, default = 'Tables.xlsx'
            The file name of the exported Excel file
        predictorBinning: bool, default = True
            If False, the 'predictorbinning' table will not be created

        """
        from xlsxwriter import Workbook

        if predictorBinning:
            tabs = {tab: getattr(self, tab) for tab in self.ApplicableTables}
        else:
            tabs = {
                tab: getattr(self, tab)
                for tab in self.ApplicableTablesNoPredictorBinning
            }

        with Workbook(
            file, options={"nan_inf_to_errors": True, "remove_timezone": True}
        ) as wb:
            for tab, data in tabs.items():
                data = data.with_columns(
                    pl.col(pl.List(pl.Categorical), pl.List(pl.Utf8))
                    .list.eval(pl.element().cast(pl.Utf8))
                    .list.join(", ")
                )
                data.write_excel(workbook=wb, worksheet=tab)
        return file
