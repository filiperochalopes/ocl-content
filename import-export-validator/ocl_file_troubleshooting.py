import json
import ndjson
import logging
import urllib.parse
import argparse

parser = argparse.ArgumentParser(
    description="Print the OCL export rows whose ids are listed as duplicates in a validator error log."
)
parser.add_argument("--error-log", required=True, help="log written by Import_Export_Validator.py")
parser.add_argument("--ocl-file", required=True, help="export.json downloaded from the OCL Source version")
args = parser.parse_args()
error_log, OCL_FILE = args.error_log, args.ocl_file

with open(OCL_FILE, 'r', encoding="utf-8-sig") as f:
    ocl_data = json.load(f)

errors = []
with open(error_log, 'r', encoding="utf-8-sig") as e:
    for line in e:
        errors.append(line.replace("ERROR: OCL has more than one concept with id ","").replace("\n",'').replace('"',''))
# print(errors)

for row in ocl_data:
    for id in errors:
        if row['id'] == id:
            print(row)
