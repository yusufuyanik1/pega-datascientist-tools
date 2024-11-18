import shutil

import streamlit as st
st.write("hello")
# import pdstools
# from pdstools.utils.cdh_utils import setup_logger
# from pdstools.utils.streamlit_utils import st_get_latest_pdstools_version

# st.set_page_config(
#     page_title="Home",
#     menu_items={
#         "Report a bug": "https://github.com/pegasystems/pega-datascientist-tools/issues",
#         "Get help": "https://pegasystems.github.io/pega-datascientist-tools/Python/examples.html",
#     },
# )


# if "log_buffer" not in st.session_state:
#     logger, st.session_state.log_buffer = setup_logger()

# """
# # Welcome to the Health Check app!

# This app helps you analyze ADMDatamart data by allowing you to generate a Health Check document with visuals as well as excel
# export for self exploration of the data.

# To be up to date with changes in the app, make sure to regularly run a `pip install --upgrade pdstools`!
# """

# pandoc_available = shutil.which("pandoc") is not None

# if not pandoc_available:
#     st.warning(
#         """
#     ⚠️ Pandoc is not available on your system. Some features of this app may not work correctly.

#     Please install Pandoc from https://pandoc.org/installing.html to ensure full functionality.
#     """
#     )


# current_version = pdstools.__version__
# latest_version = st_get_latest_pdstools_version()

# if latest_version and current_version != latest_version:
#     st.warning(
#         f"""
#     ⚠️ You are using pdstools version {current_version}, but version {latest_version} is available.

#     To update, run: `pip install --upgrade pdstools`
#     """
#     )

# import streamlit as st
# from pdstools.utils import streamlit_utils

# "# Importing the data"
# st.write(
#     """We currently support three ways to upload your own data,
# and one convenient way to test out the Health Check using a CDH Sample dataset.
# Select an option below to get started, or first configure some advanded options
# in the expanding section below."""
# )

# with st.expander("Configure advanced options", expanded=True):
#     extract_pyname_keys = st.checkbox(
#         "Extract Treatments",
#         True,
#         help="""By default, ADM has a few "Context Keys" it uses to
#         distinguish between models, such as Issue, Group, Channel, or Name.
#         However, if you've setup custom context keys that are not part of a regular
#         CDH setup, they are embedded in the "pyName" column. Setting this checkbox
#         tells us to try to extract these keys into separate columns.""",
#     )


# streamlit_utils.import_datamart(extract_pyname_keys=extract_pyname_keys)
# for key in st.session_state.keys():
#     if key not in ["dm", "params", "logger", "log_buffer"]:
#         del st.session_state[key]

# import streamlit as st
# import json
# import polars as pl
# from pdstools.utils.streamlit_utils import filter_dataframe, model_and_row_counts
# from pdstools.utils.cdh_utils import _apply_query

# """# Add custom filters"""

# """You can easily add custom filters to specify the Health Check to your needs.
# In the selectbox below, simply select the columns you wish to filter.
# For each column, a new configuration screen will be added in which you can specify
# what values you want to keep in the Health Check.
# """

# if "dm" in st.session_state:
#     expr_list = []
#     uploaded_file = st.file_uploader(
#         "Upload Filters You Downloaded Earlier", type=["json"]
#     )
#     if uploaded_file:
#         imported_filters = json.load(uploaded_file)
#         for key, val in imported_filters.items():
#             expr_list.append(pl.Expr.from_json(json.dumps(val)))

#     st.session_state["filters"] = filter_dataframe(
#         st.session_state["dm"].model_data, queries=expr_list
#     )
#     if "unfiltered_counts" not in st.session_state.keys():
#         st.session_state["unfiltered_counts"] = model_and_row_counts(
#             st.session_state["dm"].model_data
#         )
#     if st.session_state["filters"] != []:
#         filtered_modelid_count, filtered_row_count = model_and_row_counts(
#             _apply_query(st.session_state["dm"].model_data, st.session_state["filters"])
#         )
#         deserialize_exprs = {}
#         for i, expr in enumerate(st.session_state["filters"]):
#             deserialize_exprs[i] = json.loads(expr.meta.write_json())
#         data = json.dumps(deserialize_exprs)
#         st.download_button(
#             label="Download Filters",
#             data=data,
#             file_name="datamart_filters.json",
#         )
#         row_count_bar = st.progress(
#             (filtered_row_count / st.session_state["unfiltered_counts"][1]),
#             text=f"{filtered_row_count} rows are left out of {st.session_state['unfiltered_counts'][1]}",
#         )
#         model_count_bar = st.progress(
#             (filtered_modelid_count / st.session_state["unfiltered_counts"][0]),
#             text=f"{filtered_modelid_count} models are left out of {st.session_state['unfiltered_counts'][0]}",
#         )

# else:
#     st.warning("Please configure your files in the `data import` tab.")


# import logging
# import os
# from datetime import datetime
# from pathlib import Path

# import streamlit as st

# from pdstools.utils.streamlit_utils import model_selection_df
# from pdstools.utils.show_versions import show_versions
# from pdstools.utils.cdh_utils import _apply_query

# if "dm" not in st.session_state:
#     st.warning("Please configure your files in the `data import` tab.")
#     st.stop()
# logger = logging.getLogger(__name__)
# health_check, model_report = st.tabs(
#     [
#         "Overall Health Check",
#         "Individual Model Reports",
#     ]
# )

# with health_check:
#     st.title("Generate Health Check")
#     """To begin monitoring your models, you can create a Health Check document that provides a summary of all models and predictors."""
#     with st.expander("Health Check options"):
#         name = st.text_input("Customer name")
#         if name == "":
#             name = None
#         output_type = st.selectbox("Select output type", ["html"], index=0)
#         working_dir = Path(st.text_input("Change working directory", "healthCheckDir"))
#         keep_temp_files = st.checkbox("Keep temporary files", False)

#     outfile = ""
#     if "run" not in st.session_state:
#         st.session_state["runID"] = 0
#         st.session_state["run"] = {0: {}}
#     try:
#         if st.button("Generate Health Check"):
#             st.session_state["runID"] = max(list(st.session_state["run"].keys())) + 1
#             logger.info(
#                 f"Starting Health Check generation. Run ID: {st.session_state['runID']}"
#             )
#             with st.spinner("Generating Health Check..."):
#                 outfile = st.session_state["dm"].generate.health_check(
#                     name=name,
#                     output_dir=working_dir,
#                     query=st.session_state.get("filters", None),
#                     output_type=output_type,
#                     keep_temp_files=keep_temp_files,
#                     verbose=False,
#                 )
#                 if os.path.isfile(outfile):
#                     file = open(outfile, "rb")

#                 st.session_state["run"][st.session_state["runID"]] = {
#                     "name": outfile,
#                     "file": file,
#                 }

#                 if len(st.session_state["run"][st.session_state["runID"]]) == 0:
#                     st.stop()
#         if "file" in st.session_state["run"][st.session_state["runID"]]:
#             btn = st.download_button(
#                 label="Download Health Check",
#                 data=st.session_state["run"][st.session_state["runID"]]["file"],
#                 file_name=Path(
#                     st.session_state["run"][st.session_state["runID"]]["name"]
#                 ).name,
#                 key="HealthCheckDownload",
#             )
#         st.title("Create Excel Tables")
#         st.write(
#             "If you prefer conducting a custom analysis in Excel, you can easily transform your data into Excel format."
#         )
#         include_binning = st.checkbox(
#             "Include Binning",
#             False,
#             help="Including binning data may cause issues due to the size of the full data!",
#         )
#         if include_binning and st.session_state["dm"].predictor_data is None:
#             st.warning("Please upload Predictor Snapshot to include binning!")
#         if st.button("Create Tables"):
#             with st.spinner("Creating Tables..."):
#                 tablename = "ADMSnapshots.xlsx"
#                 tables = st.session_state["dm"].generate.excel_report(
#                     tablename,
#                     predictor_binning=include_binning,
#                     query=(st.session_state.get("filters", None)),
#                 )
#                 st.session_state["run"][st.session_state["runID"]]["tables"] = tablename
#                 st.session_state["run"][st.session_state["runID"]]["tablefile"] = open(
#                     tables, "rb"
#                 )

#             btn = st.download_button(
#                 label="Download additional tables",
#                 data=st.session_state["run"][st.session_state["runID"]]["tablefile"],
#                 file_name=st.session_state["run"][st.session_state["runID"]]["tables"],
#                 key="TablesDownload",
#             )

#     except Exception as e:
#         logger.exception(f"An error occurred during Health Check generation: {e}")
#         if "health_check_error_download" not in st.session_state:
#             st.error(f"An error occurred: {e}")
#             log_file_path = (
#                 f"pdstools_error_log_{datetime.now().isoformat().replace(':', '_')}.txt"
#             )
#             with open(log_file_path, "w") as log_file:
#                 log_file.write(st.session_state.log_buffer.getvalue())
#             with open(log_file_path, "rb") as f:
#                 btn = st.download_button(
#                     label="Download error log",
#                     data=f,
#                     file_name=Path(log_file_path).name,
#                     key="health_check_error_download",
#                 )

#     finally:
#         if "log_file_path" in locals() and os.path.isfile(log_file_path):
#             os.remove(log_file_path)

# if st.session_state["dm"].predictor_data is not None:
#     with model_report:
#         try:
#             if "working_dir" not in locals():
#                 working_dir = "healthCheckDir"
#             if "model_selection_df" not in st.session_state:
#                 st.session_state["model_selection_df"] = model_selection_df(
#                     df=_apply_query(
#                         st.session_state["dm"].combined_data,
#                         st.session_state.get("filters", None),
#                     ),
#                     context_keys=st.session_state["dm"].context_keys,
#                 )
#             st.write("Please choose the models for which you wish to generate a report")
#             edited_df = st.data_editor(
#                 st.session_state["model_selection_df"],
#                 disabled=st.session_state["dm"].context_keys + ["Name"],
#                 use_container_width=True,
#             )
#             st.session_state["only_active_predictors"] = st.checkbox(
#                 label="Show only active predictors",
#                 help="The ADM service automatically determines which predictors are used by the models, based on the individual predictive performance and the correlation between predictors. For example, the predictors with a low predictive performance do not become active. When predictors are highly correlated, only the best-performing predictor is used.",
#                 value=True,
#             )
#             st.session_state["selected_models"] = edited_df.loc[
#                 edited_df["Generate Report"] == True
#             ]["ModelID"].to_list()
#             st.write(f"{len(st.session_state['selected_models'])} models are selected")
#             if len(st.session_state["selected_models"]) > 0:
#                 if st.button("Create Model Report(s) for selected model(s)"):
#                     with st.spinner("Running Model Reports..."):
#                         progress_bar = st.progress(
#                             0,
#                             text=f"Generated {0} of {len(st.session_state['selected_models'])}",
#                         )
#                         progress_text = st.empty()

#                         def update_progress(current, total):
#                             progress = current / total
#                             progress_bar.progress(
#                                 progress, text=f"Generated {current} of {total}"
#                             )

#                         outfile = st.session_state["dm"].generate.model_reports(
#                             model_ids=st.session_state["selected_models"],
#                             name="",
#                             output_dir=working_dir,
#                             query=st.session_state.get("filters", None),
#                             only_active_predictors=st.session_state[
#                                 "only_active_predictors"
#                             ],
#                             output_type="html",
#                             keep_temp_files=keep_temp_files,
#                             progress_callback=update_progress,
#                         )
#                         if os.path.isfile(outfile):
#                             file = open(outfile, "rb")
#                         st.session_state["model_report_files"] = file
#                         st.session_state["model_report_name"] = (
#                             outfile.name
#                             if len(st.session_state["selected_models"]) == 1
#                             else "ModelReports.zip"
#                         )

#                         btn = st.download_button(
#                             label="Download Model Reports",
#                             data=st.session_state["model_report_files"],
#                             file_name=st.session_state["model_report_name"],
#                             key="ModelReportDownload",
#                         )
#                         progress_bar.empty()
#                         progress_text.empty()
#                         st.balloons()
#         except Exception as e:
#             logger.exception("An error occurred during Model Report generation")
#             if "model_report_error_download" not in st.session_state:
#                 st.error(f"An error occurred: {e}")
#                 log_file_path = f"pdstools_error_log_{datetime.now().isoformat().replace(':', '_')}.txt"
#                 with open(log_file_path, "w") as log_file:
#                     log_file.write(st.session_state.log_buffer.getvalue())
#                     log_file.write("\n\n--- Version Information ---\n")
#                     log_file.write(show_versions(print_output=False))
#                 with open(log_file_path, "rb") as f:
#                     btn = st.download_button(
#                         label="Download error log",
#                         data=f,
#                         file_name=Path(log_file_path).name,
#                         key="model_report_error_download",
#                     )

#         finally:
#             if "log_file_path" in locals() and os.path.isfile(log_file_path):
#                 os.remove(log_file_path)
# else:
#     st.info(
#         "You can generate individual model reports if you provide Predictor Snapshot in 'Data Import' stage.",
#         icon="ℹ️",
#     )
