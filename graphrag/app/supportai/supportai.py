import os
import json
import uuid
import logging
import boto3
import time
import re
import pyTigerGraph as tg
from pyTigerGraph import TigerGraphConnection

from common.config import embedding_dimension, graphrag_config
from common.py_schemas.schemas import (
    # GraphRAGResponse,
    CreateIngestConfig,
    # LoadingInfo,
    # SupportAIInitConfig,
    # SupportAIMethod,
    # SupportAIQuestion,
)

logger = logging.getLogger(__name__)

def init_supportai(conn: TigerGraphConnection, graphname: str) -> tuple[dict, dict]:
    # need to open the file using the absolute path
    ver = conn.getVer().split(".")

    current_schema = conn.gsql("""USE GRAPH {}\n ls""".format(graphname))

    supportai_queries = [
        "common/gsql/supportai/Scan_For_Updates.gsql",
        "common/gsql/supportai/Update_Vertices_Processing_Status.gsql",
        "common/gsql/supportai/Selected_Set_Display.gsql",
        "common/gsql/supportai/retrievers/GraphRAG_Hybrid_Search_Display.gsql",
        "common/gsql/supportai/retrievers/GraphRAG_Community_Search_Display.gsql",
        #"common/gsql/supportai/retrievers/Chunk_Sibling_Search.gsql",
        #"common/gsql/supportai/retrievers/Content_Similarity_Search.gsql",
        #"common/gsql/supportai/retrievers/GraphRAG_Hybrid_Search.gsql",
        #"common/gsql/supportai/retrievers/GraphRAG_Community_Search.gsql",
    ]

    if "- VERTEX ResolvedEntity" in current_schema:
        schema_res="Schema already exists, skipped"
    else:
        file_path = "common/gsql/supportai/SupportAI_Schema.gsql"
        with open(file_path, "r") as f:
            schema = f.read()
        if graphrag_config.get("use_graph_schema", True):
            schema_append = "EDGE CONTAINS_ENTITY(FROM DocumentChunk, TO Entity"
            for vert in conn.getVertexTypes():
                schema_append += f"""|FROM DocumentChunk, TO {vert}"""
            schema_append += ")"
            schema = schema.replace("EDGE CONTAINS_ENTITY(FROM DocumentChunk, TO Entity)", schema_append)
        schema_res = conn.gsql(
            """USE GRAPH {}\n{}\nRUN SCHEMA_CHANGE JOB add_supportai_schema""".format(
                graphname, schema
            )
        )


    if f"  - ResolvedEntity:\n    - embedding(Dimension={embedding_dimension}" in current_schema:
        schema_res+=" Embeddding schema already exists, skipped"
    else:
        if int(ver[0]) >= 4 and int(ver[1]) >= 2:
            file_path = "common/gsql/supportai/SupportAI_Schema_Native_Vector.gsql"
            with open(file_path, "r") as f:
                schema = f.read()
            if embedding_dimension != 1536:
                schema = schema.replace(
                    "dimension=1536",
                    f"dimension={embedding_dimension}",
                )
            schema_res += " "
            schema_res += conn.gsql(
                """USE GRAPH {}\n{}\nRUN SCHEMA_CHANGE JOB add_supportai_vector""".format(
                    graphname, schema
                )
            )

            logger.info(f"Installing GDS library")
            q_res = conn.gsql(
                """USE GLOBAL\nimport package gds\ninstall function gds.**"""
            )
            logger.info(f"Done installing GDS library with status {q_res}")

            supportai_queries.extend([
                "common/gsql/supportai/retrievers/Content_Similarity_Vector_Search.gsql",
                "common/gsql/supportai/retrievers/Chunk_Sibling_Vector_Search.gsql",
                "common/gsql/supportai/retrievers/GraphRAG_Community_Vector_Search.gsql",
                "common/gsql/supportai/retrievers/GraphRAG_Hybrid_Vector_Search.gsql",
            ])
        else:
            raise Exception(f"Vector feature is not supported by the current TigerGraph version: {ver}")

    if "- doc_chunk_epoch_processed_index" in current_schema:
        index_res="Index already exists, skipped"
    else:
        file_path = "common/gsql/supportai/SupportAI_IndexCreation.gsql"
        with open(file_path) as f:
            index = f.read()
        index_res = conn.gsql(
            """USE GRAPH {}\n{}\nRUN SCHEMA_CHANGE JOB add_supportai_indexes""".format(
                graphname, index
            )
        )

    for filename in supportai_queries:
        logger.info(f"Creating supportai query {filename}")
        with open(f"{filename}", "r") as f:
            q_body = f.read()
        q_name, extension = os.path.splitext(os.path.basename(filename))
        q_res = conn.gsql(
            """USE GRAPH {}\nBEGIN\n{}\nEND\n""".format(
                conn.graphname, q_body
            )
        )
        logger.info(f"Done creating supportai query {q_name} with status {q_res}")

    logger.info(f"Installing supportai queries all together")
    query_res = conn.gsql(
        """USE GRAPH {}\nINSTALL QUERY ALL\n""".format(
            conn.graphname
        )
    )
    logger.info(f"Done installing supportai query all with status {query_res}")

    return schema_res, index_res, query_res


def trigger_bedrock_bda(input_bucket, output_bucket, region, aws_access_key, aws_secret_key, data_source_config={}):
    logger.info(f"Triggering Bedrock Data Automation {region}")
    s3 = boto3.client('s3', region_name=region, aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key)
    bda_client = boto3.client('bedrock-data-automation', region_name=region, aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key)
    bda_runtime_client = boto3.client('bedrock-data-automation-runtime', region_name=region, aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key)

    # Get AWS account ID from STS
    sts_client = boto3.client('sts', region_name=region, aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key)
    account_id = sts_client.get_caller_identity()['Account']

    # Set default configuration values
    # Configure granularity options
    granularity_types = data_source_config.get('granularity', ["DOCUMENT", "ELEMENT"])

    # Configure text format options
    text_format_types = data_source_config.get('text_format', ["MARKDOWN"])

    project_arn = None
    try:
        # there is a bug in AWS bedrock, it does not delete projects properly, so here
        # we generate random project name each time below
        # Delete existing project if it exists
        # existing_projects = bda_client.list_data_automation_projects()["projects"]
        # for project in existing_projects:
        #     if project["projectName"] == "barclays-preprocessing-project":
        #         bda_client.delete_data_automation_project(projectArn=project["projectArn"])
        #         time.sleep(2)
        #         break

        # Create BDA project
        logger.info(f"Creating BDA project")
        project_name = f"bda-preprocessing-{uuid.uuid4().hex[:6]}"
        logger.info(f"Created before  BDA project {project_name}")
        project_response = bda_client.create_data_automation_project(
            projectName=project_name,
            projectDescription='Preprocessing multi data formats using bedrock data automation',
            projectStage='DEVELOPMENT',
            standardOutputConfiguration={
                "document": {
                    "extraction": {
                        "granularity": {"types": granularity_types},
                        "boundingBox": {"state": "ENABLED"}
                    },
                    "generativeField": {"state": "ENABLED"},
                    "outputFormat": {
                        "textFormat": {"types": text_format_types},
                        "additionalFileFormat": {"state": "ENABLED"}
                    }
                }}
        )

        project_arn = project_response['projectArn']
        logger.info(f"Created after BDA project {project_name} with ARN {project_arn}")
        # Get file names from S3
        response = s3.list_objects_v2(Bucket=input_bucket)
        objects = response.get('Contents', [])
        logger.info(f"Found {len(objects)} objects in S3 bucket {input_bucket}")
        job_results = []

        # Launch all BDA jobs first and collect job_arns
        for obj in objects:
            time.sleep(2)
            file_key = obj['Key']
            input_s3_uri = f's3://{input_bucket}/{file_key}'
            output_s3_uri = f's3://{output_bucket}/bda/output/{file_key}'

            bda_response = bda_runtime_client.invoke_data_automation_async(
                inputConfiguration={
                    's3Uri': input_s3_uri
                },
                outputConfiguration={
                    's3Uri': output_s3_uri
                },
                dataAutomationConfiguration={
                    'dataAutomationProjectArn': project_arn,
                    'stage': 'DEVELOPMENT'
                },
                dataAutomationProfileArn=f'arn:aws:bedrock:{region}:{account_id}:data-automation-profile/us.data-automation-v1'
            )
            job_arn = bda_response.get('invocationArn')
            logger.info(f"Created BDA job for file {file_key} with job ID {job_arn}")
            job_results.append({
                'file': file_key,
                'jobId': job_arn,
                'status': None
            })

        # Poll all jobs' statuses
        for job in job_results:
            job_arn = job['jobId']
            file_key = job['file']
            while True:
                status_response = bda_runtime_client.get_data_automation_status(invocationArn=job_arn)
                status = status_response.get('status')
                if status in ['Success', 'FAILED', 'STOPPED']:
                    if status not in ['Success']:
                        logger.info(f"ERROR: job not success for {job_arn} on file {file_key}with end status {status}")
                    else:
                        logger.info(f"BDA job {job_arn} on file {file_key} completed successfully.")
                    break
                time.sleep(1)
            if status != 'Success':
                logger.error(f"BDA job {job_arn} failed with status: {status}")
            else:
                logger.info(f"BDA job {job_arn} completed successfully.")
            job['status'] = status

        logger.info(f"Accomplished {len(job_results)} BDA jobs")

        return {
            'statusCode': 200,
            'message': f'Processed {len(job_results)} BDA jobs',
            'jobs': job_results
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'error': str(e)
        }

    finally:
        # Clean up: Delete the BDA project after all jobs are completed
        if project_arn:
            try:
                logger.info(f"Cleaning up BDA project: {project_arn}")
                delete_response = bda_client.delete_data_automation_project(projectArn=project_arn)
                logger.info(f"Successfully deleted BDA project: {delete_response}")
            except Exception as cleanup_error:
                logger.warning(f"Failed to delete BDA project {project_arn}: {cleanup_error}")
                # Don't fail the entire operation if cleanup fails


def create_ingest(
    graphname: str,
    ingest_config: CreateIngestConfig,
    conn: TigerGraphConnection,
):
    # Check for invalid combination of multi format and non-s3 data source
    if ingest_config.file_format.lower() == "multi" and ingest_config.data_source.lower() != "s3":
        raise Exception(
            "AWS Bedrock BDA preprocessing with 'multi' file format is only supported for S3 data sources.")

    if ingest_config.file_format.lower() == "json" or ingest_config.file_format.lower() == "multi":
        file_path = "common/gsql/supportai/SupportAI_InitialLoadJSON.gsql"

        with open(file_path) as f:
            ingest_template = f.read()
        ingest_template = ingest_template.replace("@uuid@", str(uuid.uuid4().hex))
        doc_id = ingest_config.loader_config.get("doc_id_field", "doc_id")
        doc_text = ingest_config.loader_config.get("content_field", "content")
        doc_type = ingest_config.loader_config.get("doc_type", "")
        ingest_template = ingest_template.replace('"doc_id"', '"{}"'.format(doc_id))
        ingest_template = ingest_template.replace('"content"', '"{}"'.format(doc_text))
        ingest_template = ingest_template.replace('"doc_type"', '"{}"'.format(doc_type))

    if ingest_config.file_format.lower() == "csv":
        file_path = "common/gsql/supportai/SupportAI_InitialLoadCSV.gsql"

        with open(file_path) as f:
            ingest_template = f.read()
        ingest_template = ingest_template.replace("@uuid@", str(uuid.uuid4().hex))
        separator = ingest_config.get("separator", "|")
        header = ingest_config.get("header", "true")
        eol = ingest_config.get("eol", "\n")
        quote = ingest_config.get("quote", "double")
        ingest_template = ingest_template.replace('"|"', '"{}"'.format(separator))
        ingest_template = ingest_template.replace('"true"', '"{}"'.format(header))
        ingest_template = ingest_template.replace('"\\n"', '"{}"'.format(eol))
        ingest_template = ingest_template.replace('"double"', '"{}"'.format(quote))

    file_path = "common/gsql/supportai/SupportAI_DataSourceCreation.gsql"

    with open(file_path) as f:
        data_stream_conn = f.read()

    # assign unique identifier to the data stream connection

    data_stream_conn = data_stream_conn.replace(
        "@source_name@", "SupportAI_" + graphname + "_" + str(uuid.uuid4().hex)
    )

    # check the data source and create the appropriate connection
    res = {"data_source": ingest_config.data_source.lower()}

    if ingest_config.data_source.lower() == "s3":
        data_conf = ingest_config.data_source_config
        aws_access_key = data_conf.get("aws_access_key", None)
        aws_secret_key = data_conf.get("aws_secret_key", None)

        if aws_access_key is None or aws_secret_key is None:
            raise Exception("AWS credentials not provided")

        connector = {
            "type": "s3",
            "access.key": aws_access_key,
            "secret.key": aws_secret_key,
        }

        data_stream_conn = data_stream_conn.replace(
            "@source_config@", json.dumps(connector)
        )

        if ingest_config.file_format.lower() == "multi":
            input_bucket = data_conf.get("input_bucket", None)
            output_bucket = data_conf.get("output_bucket", None)
            region_name = data_conf.get("region_name", None)

            if input_bucket is None or output_bucket is None or region_name is None:
                raise Exception("Input bucket, output bucket, or region name not provided")

            try:
                bedrock_bda_result = trigger_bedrock_bda(
                    input_bucket, output_bucket, region_name, aws_access_key, aws_secret_key, data_conf)
                if bedrock_bda_result.get("statusCode") != 200:
                    raise Exception(f"Bedrock BDA failed: {bedrock_bda_result}")

                #status check of bda, start once completion
                # --- Begin: S3 markdown extraction and TigerGraph loading ---
                # Possiblely we can download the files locally and then process them with next conn.runDocumentIngest() after it supports folder
                logger.info(
                    f"Starting S3 markdown extraction and TigerGraph loading...")

                job_uids = [job.get("jobId").split("/")[-1] for job in bedrock_bda_result.get("jobs")]

                s3 = boto3.client('s3', region_name=region_name, aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key)
                prefix = 'bda/output/'

                paginator = s3.get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=output_bucket, Prefix=prefix)
                processed_files = []

                load_job_created = conn.gsql("USE GRAPH {}\n".format(graphname) + ingest_template)
                load_job_id = load_job_created.split(":")[1].strip(" [").strip(" ").strip(".").strip("]")
                res["load_job_id"] = load_job_id
                res["data_source_id"] = "DocumentContent"
                for page in pages:
                    if 'Contents' not in page:
                        continue
                    for obj in page['Contents']:
                        key = obj['Key']
                        if key.endswith('/0/standard_output/0/result.md'):
                            path_parts = key.split('/')
                            if len(path_parts) >= 7:
                                file_name = path_parts[-6]
                                file_uuid = path_parts[-5]
                                if file_uuid not in job_uids:
                                    continue

                                response = s3.get_object(Bucket=output_bucket, Key=key)
                                content = response['Body'].read().decode('utf-8')
                                base_path = "/".join(path_parts[:-1]) + "/assets/"

                                # Find and log image matches before replacement
                                matches = re.findall(r'!\[([^\]]*)\]\(\./([^)]+)\)', content)
                                content = re.sub(r'!\[([^\]]*)\]\(\./([^)]+)\)', lambda m: f'![{m.group(1)}](s3://{output_bucket}/{base_path}{m.group(2)})', content)
                                doc_id = f"{file_name}"
                                # Prepare API payload
                                payload = json.dumps({"doc_id": doc_id, "doc_type": "markdown", "content": content})

                                #CALL API
                                conn.runLoadingJobWithData(payload, "DocumentContent", load_job_id)
                                processed_files.append({
                                    'file_path': key,
                                    'doc_id': doc_id,
                                })
                                # Loading into TigerGraph is now handled elsewhere.
                                logger.info(f"Data uploading done for file: {key} with doc_id: {doc_id}")
                res["processed_files"] = processed_files
                logger.info(
                    f"Processed {len(processed_files)} markdown files from S3 and loaded into TigerGraph.")
                # --- End: S3 markdown extraction and TigerGraph loading ---
            except Exception as e:
                logger.error(f"Error during Bedrock BDA preprocessing: {e}")
                return {"error": str(e), "stage": "bedrock_bda_preprocessing"}
            return res

    elif ingest_config.data_source.lower() == "azure":
        if ingest_config.data_source_config.get("account_key") is not None:
            connector = {
                "type": "abs",
                "account.key": ingest_config.data_source_config["account_key"],
            }
        elif ingest_config.data_source_config.get("client_id") is not None:
            # verify that the client secret is also provided
            if ingest_config.data_source_config.get("client_secret") is None:
                raise Exception("Client secret not provided")
            # verify that the tenant id is also provided
            if ingest_config.data_source_config.get("tenant_id") is None:
                raise Exception("Tenant id not provided")
            connector = {
                "type": "abs",
                "client.id": ingest_config.data_source_config["client_id"],
                "client.secret": ingest_config.data_source_config["client_secret"],
                "tenant.id": ingest_config.data_source_config["tenant_id"],
            }
        else:
            raise Exception("Azure credentials not provided")
        data_stream_conn = data_stream_conn.replace(
            "@source_config@", json.dumps(connector)
        )
    elif ingest_config.data_source.lower() == "gcs":
        # verify that the correct fields are provided
        if ingest_config.data_source_config.get("project_id") is None:
            raise Exception("Project id not provided")
        if ingest_config.data_source_config.get("private_key_id") is None:
            raise Exception("Private key id not provided")
        if ingest_config.data_source_config.get("private_key") is None:
            raise Exception("Private key not provided")
        if ingest_config.data_source_config.get("client_email") is None:
            raise Exception("Client email not provided")
        connector = {
            "type": "gcs",
            "project_id": ingest_config.data_source_config["project_id"],
            "private_key_id": ingest_config.data_source_config["private_key_id"],
            "private_key": ingest_config.data_source_config["private_key"],
            "client_email": ingest_config.data_source_config["client_email"],
        }
        data_stream_conn = data_stream_conn.replace(
            "@source_config@", json.dumps(connector)
        )
    elif ingest_config.data_source.lower() == "local":
        pass
    else:
        raise Exception("Data source not implemented")

    load_job_created = conn.gsql("USE GRAPH {}\n".format(graphname) + ingest_template)
    res["load_job_id"] = load_job_created.split(":")[1].strip(" [").strip(" ").strip(".").strip("]")
    if ingest_config.data_source_config:
        res["data_path"] = ingest_config.data_source_config.get("data_path", "")

    if ingest_config.data_source.lower() == "local":
        res["data_source_id"] = "DocumentContent"
    else:
        data_source_created = conn.gsql(
            "USE GRAPH {}\n".format(graphname) + data_stream_conn
        )
        res["data_source_id"] = data_source_created.split(":")[1].strip(" [").strip(" ").strip(".").strip("]")

    return res
