import os
import traceback
from pathlib import Path

import streamlit as st

from pdstools.utils.streamlit_utils import model_selection_df

if "dm" not in st.session_state:
    st.warning("Please configure your files in the `data import` tab.")
    st.stop()

if "data_is_cached" not in st.session_state:
    st.session_state["data_is_cached"] = False

health_check, model_report = st.tabs(
    [
        "Overall Health Check",
        "Individual Model Reports",
    ]
)

with health_check:
    st.title("Generate Health Check")
    """To begin monitoring your models, you can create a Health Check document that provides a summary of all models and predictors."""
    with st.expander("Health Check options"):
        name = st.text_input("Customer name")
        if name == "":
            name = None
        output_type = st.selectbox("Select output type", ["html"], index=0)
        working_dir = Path(st.text_input("Change working directory", "healthCheckDir"))
        delete_temp_files = st.checkbox("Remove temporary files", True)

    outfile = ""
    if "run" not in st.session_state:
        st.session_state["runID"] = 0
        st.session_state["run"] = {0: {}}
    try:
        if st.button("Generate Health Check"):
            st.session_state["runID"] = max(list(st.session_state["run"].keys())) + 1

            with st.spinner("Generating Health Check..."):
                outfile = (
                    st.session_state["dm"]
                    .applyGlobalQuery(st.session_state.get("filters", None))
                    .generate_health_check(
                        name=name,
                        output_type=output_type,
                        working_dir=working_dir,
                        delete_temp_files=delete_temp_files,
                        output_to_file=True,
                        verbose=True,
                    )
                )
                if os.path.isfile(outfile):
                    file = open(outfile, "rb")

                st.session_state["run"][st.session_state["runID"]] = {
                    "name": outfile,
                    "file": file,
                }

                if len(st.session_state["run"][st.session_state["runID"]]) == 0:
                    st.stop()
        if "file" in st.session_state["run"][st.session_state["runID"]]:
            btn = st.download_button(
                label="Download Health Check",
                data=st.session_state["run"][st.session_state["runID"]]["file"],
                file_name=Path(
                    st.session_state["run"][st.session_state["runID"]]["name"]
                ).name,
                key="HealthCheckDownload",
            )

        st.title("Create Excel Tables")
        st.write(
            "If you prefer conducting a custom analysis in Excel, you can easily transform your data into Excel format."
        )
        include_binning = st.checkbox(
            "Include Binning",
            False,
            help="Including binning data may cause issues due to the size of the full data!",
        )
        if include_binning and st.session_state["dm"].predictorData is None:
            st.warning("Please upload Predictor Snapshot to include binning!")
        if st.button("Create Tables"):
            with st.spinner("Creating Tables..."):
                tablename = "ADMSnapshots.xlsx"
                tables = (
                    st.session_state["dm"]
                    .applyGlobalQuery(st.session_state.get("filters", None))
                    .exportTables(tablename)
                )
                st.session_state["run"][st.session_state["runID"]]["tables"] = tablename
                st.session_state["run"][st.session_state["runID"]]["tablefile"] = open(
                    tables, "rb"
                )

            btn = st.download_button(
                label="Download additional tables",
                data=st.session_state["run"][st.session_state["runID"]]["tablefile"],
                file_name=st.session_state["run"][st.session_state["runID"]]["tables"],
                key="TablesDownload",
            )

    except Exception as e:
        st.error(f"""An error occured: {e}""")
        traceback_str = traceback.format_exc()
        with open(working_dir / "log.txt", "a") as f:
            f.write(traceback_str)
        with open(working_dir / "log.txt", "rb") as f:
            btn = st.download_button(
                label="Download error log",
                data=f,
                file_name="errorlog.txt",
                key="ErrorLogDownload",
            )

        for filename in os.listdir(working_dir):
            file_path = os.path.join(working_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

if st.session_state["dm"].predictorData is not None:
    with model_report:
        try:
            if "working_dir" not in locals():
                working_dir = "healthCheckDir"
            if "model_selection_df" not in st.session_state:
                if "filters" in st.session_state:
                    st.session_state["model_selection_df"] = model_selection_df(
                        df=st.session_state["dm"]._apply_query(
                            st.session_state["dm"].combinedData,
                            st.session_state["filters"],
                        ),
                        context_keys=st.session_state["dm"].context_keys,
                    )
                else:
                    st.session_state["model_selection_df"] = model_selection_df(
                        df=st.session_state["dm"].combinedData,
                        context_keys=st.session_state["dm"].context_keys,
                    )

            st.write("Please choose the models for which you wish to generate a report")
            edited_df = st.data_editor(
                st.session_state["model_selection_df"],
                disabled=st.session_state["dm"].context_keys + ["Name"],
                use_container_width=True,
            )
            st.session_state["only_active_predictors"] = st.checkbox(
                label="Show only active predictors",
                help="The ADM service automatically determines which predictors are used by the models, based on the individual predictive performance and the correlation between predictors. For example, the predictors with a low predictive performance do not become active. When predictors are highly correlated, only the best-performing predictor is used.",
                value=True,
            )
            st.session_state["selected_models"] = edited_df.loc[
                edited_df["Generate Report"] == True
            ]["ModelID"].to_list()
            st.write(f"{len(st.session_state['selected_models'])} models are selected")
            if len(st.session_state["selected_models"]) > 0:
                if st.button("Create Model Report(s) for selected model(s)"):
                    with st.spinner("Running Model Reports..."):
                        progress_bar = st.progress(
                            0,
                            text=f"Generated {0} of {len(st.session_state['selected_models'])}",
                        )
                        progress_text = st.empty()

                        def update_progress(current, total):
                            progress = current / total
                            progress_bar.progress(
                                progress, text=f"Generated {current} of {total}"
                            )

                        outfile = (
                            st.session_state["dm"]
                            .applyGlobalQuery(st.session_state.get("filters", None))
                            .generate_model_reports(
                                name="",
                                working_dir=working_dir,
                                model_list=st.session_state["selected_models"],
                                output_type="html",
                                only_active_predictors=st.session_state[
                                    "only_active_predictors"
                                ],
                                progress_callback=update_progress,
                            )
                        )
                        if os.path.isfile(outfile):
                            file = open(outfile, "rb")
                        st.session_state["model_report_files"] = file
                        st.session_state["model_report_name"] = (
                            outfile.name
                            if st.session_state["selected_models"] == 1
                            else "ModelReports"
                        )

                        btn = st.download_button(
                            label="Download Model Reports",
                            data=st.session_state["model_report_files"],
                            file_name=st.session_state["model_report_name"],
                            key="ModelReportDownload",
                        )
                        progress_bar.empty()
                        progress_text.empty()
                        st.balloons()
                        st.session_state["data_is_cached"] = False
        except Exception as e:
            st.error(f"""An error occured: {e}""")
            traceback_str = traceback.format_exc()
            st.session_state["data_is_cached"] = False
            with open(working_dir / "log.txt", "a") as f:
                f.write(traceback_str)
            with open(working_dir / "log.txt", "rb") as f:
                btn = st.download_button(
                    label="Download error log",
                    data=f,
                    file_name="errorlog.txt",
                    key="ErrorLogDownload",
                )

            for filename in os.listdir(working_dir):
                file_path = os.path.join(working_dir, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
else:
    st.info(
        "You can generate individual model reports if you provide Predictor Snapshot in 'Data Import' stage.",
        icon="ℹ️",
    )
