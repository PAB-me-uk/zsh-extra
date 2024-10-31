# %%
import json
import os
from copy import deepcopy

import yaml

RESOURCES_DIRECTORY = "/workspace/calypso/data-pipelines/resources"
LEN_RESOURCES_DIRECTORY = len(RESOURCES_DIRECTORY)
TEMP_JOB_DIRECTORY = os.path.join(RESOURCES_DIRECTORY, "_temp_")

ENV_SCHEMA_PREFIX = "p_burridge_"
ENV_CATALOG_IDENTIFIER = "primary_dev_na"


def yield_job_definitions():
    for path, _, files in os.walk(RESOURCES_DIRECTORY):
        for file in files:
            if file.endswith(".yml"):
                contents = yaml.load(open(os.path.join(path, file)), Loader=yaml.SafeLoader)
                yield from contents["resources"]["jobs"].items()


def find_job_with_sql_task(end_of_sql_file_name):
    jobs = yield_job_definitions()
    for job_name, job in jobs:
        for task in job.get("tasks", []):
            if "sql_task" in task and task["sql_task"]["file"]["path"].endswith(
                end_of_sql_file_name
            ):
                return (job_name, job, task)


def get_parameters_for_sql_task(job, task):
    parameters = {
        parameter["name"]: parameter["default"] for parameter in job.get("parameters", [])
    } | task["sql_task"].get("parameters", {})
    return {
        key: value.replace("${var.ENV_CATALOG_IDENTIFIER}", ENV_CATALOG_IDENTIFIER).replace(
            "${var.ENV_SCHEMA_PREFIX}", ENV_SCHEMA_PREFIX
        )
        for key, value in parameters.items()
    }


def find_parameters_for_sql_task(end_of_sql_file_name):
    job_name, job, task = find_job_with_sql_task(end_of_sql_file_name)
    return get_parameters_for_sql_task(job, task)


def create_temp_job_for_sql_task(end_of_sql_file_name):
    job_name, job, task = find_job_with_sql_task(end_of_sql_file_name)
    parameters = get_parameters_for_sql_task(job, task)
    task = deepcopy(task)
    if "depends_on" in task:
        del task["depends_on"]
    task["sql_task"]["parameters"] = parameters
    task

    structure = {
        "resources": {
            "jobs": {
                "temp_job": {
                    "name": "temp_job_${bundle.target}",
                    "permissions": [
                        {"group_name": "SG-Databricks-Engineering", "level": "CAN_MANAGE_RUN"}
                    ],
                    "tasks": [task],
                }
            }
        }
    }
    print(json.dumps(structure, indent=2))

    os.makedirs(TEMP_JOB_DIRECTORY, exist_ok=True)
    output_file = os.path.join(TEMP_JOB_DIRECTORY, "_temp_job.yml")
    with open(output_file, "w") as file:
        yaml.dump(structure, file, default_flow_style=False)

    print()
    print(output_file)
    print()
    print(f"Job definition saved to {output_file}")


def inject_parameters_into_sql_file(sql_file):
    end_of_sql_file_path = sql_file.split("/sql/")[-1]

    parameters = find_parameters_for_sql_task(end_of_sql_file_path)

    output = ["%sql\n"]
    with open(os.path.join(RESOURCES_DIRECTORY, sql_file)) as file:
        while line := file.readline():
            if "{{" in line:
                new_line = (
                    line.replace("\n", "")
                    .replace("{{", "'{")
                    .replace("}}", "}'")
                    .format(**parameters)
                )
                output.append(f"-- [ORIGINAL] {line}")
                output.append(f"{new_line} -- [REPLACEMENT]\n")
            elif "CREATE OR REPLACE" in line:
                output.append(f"-- [ORIGINAL] {line}")
            else:
                output.append(f"{line}")

    print("".join(output))
