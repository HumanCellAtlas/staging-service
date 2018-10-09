import re
from datetime import datetime

import requests
from sqlalchemy import create_engine, MetaData
from sqlalchemy.exc import OperationalError, IntegrityError, DatabaseError

from .exceptions import UploadException
from .upload_config import UploadDbConfig

config = UploadDbConfig()
engine = create_engine(config.pgbouncer_uri, pool_size=1)
meta = MetaData(engine, reflect=True)
record_type_table_map = {
    "upload_area": meta.tables['upload_area'],
    "file": meta.tables['file'],
    "notification": meta.tables['notification'],
    "validation": meta.tables['validation'],
    "checksum": meta.tables['checksum']
}


def create_pg_record(record_type, prop_vals_dict):
    prop_vals_dict["created_at"] = datetime.utcnow()
    prop_vals_dict["updated_at"] = datetime.utcnow()
    table = record_type_table_map[record_type]
    ins = table.insert().values(prop_vals_dict)
    try:
        run_query(ins)
    except IntegrityError as e:
        if re.search("duplicate key value violates unique constraint", e.orig.pgerror):
            raise UploadException(status=requests.codes.conflict,
                                  title=f"{record_type} Already Exists",
                                  detail=f"{record_type} {prop_vals_dict['id']} already exists")
        else:
            raise e


def update_pg_record(record_type, prop_vals_dict):
    record_id = prop_vals_dict["id"]
    del prop_vals_dict["id"]
    prop_vals_dict["updated_at"] = datetime.utcnow()
    table = record_type_table_map[record_type]
    update = table.update().where(table.c.id == record_id).values(prop_vals_dict)
    run_query(update)


def get_pg_record(record_type, record_id):
    table = record_type_table_map[record_type]
    select = table.select().where(table.c.id == record_id)
    result = run_query(select)
    column_keys = result.keys()
    rows = result.fetchall()
    if len(rows) == 0:
        return None
    elif len(rows) > 1:
        raise RuntimeError(f"There is more than 1 {record_type} with ID {record_id}!")
    else:
        output = {}
        for idx, val in enumerate(rows[0]):
            column = column_keys[idx]
            output[column] = val
        return output


# Engine.dispose() protects us from situations where the client thinks it has
# an active connection but for some reason it is inactive. Potential causes
# include network issues or pgbouncer dropping inactive client connections after
# a long idle timeout. Sometimes its difficult to determine how long AWS actually
# keeps old lambda containers warmed up and waiting. This code path should not be
# followed often, but it is a good protective measure.

def run_query(query):
    try:
        results = engine.execute(query)
    except (OperationalError, DatabaseError) as e:
        engine.dispose()
        results = engine.execute(query)
    return results


def run_query_with_params(query, params):
    try:
        results = engine.execute(query, params)
    except (OperationalError, DatabaseError) as e:
        engine.dispose()
        results = engine.execute(query, params)
    return results
