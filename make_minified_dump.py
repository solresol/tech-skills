#!/usr/bin/env python3
"""Create a minified SQL dump stripping html_doc_cache.content."""
import argparse
import configparser
import subprocess
import os


def build_env(password):
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    return env


def main():
    parser = argparse.ArgumentParser(description="Create minified database dump")
    parser.add_argument("--config", default="db.conf", help="Config file with DB details")
    parser.add_argument("--output", default="techskills.sql", help="Output SQL file")
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.config)

    src = config["database"]
    dst = config["minified"]

    if src["dbname"] == dst["dbname"]:
        raise ValueError("minified database name must differ from production database name")

    src_env = build_env(src["password"])
    dst_env = build_env(dst["password"])

    src_host = src.get("hostname", "localhost")
    src_port = src.get("port", "5432")
    dst_host = dst.get("hostname", "localhost")
    dst_port = dst.get("port", "5432")

    # 1. drop any existing destination database
    subprocess.run([
        "dropdb",
        "--if-exists",
        "-h", dst_host,
        "-p", str(dst_port),
        "-U", dst["user"],
        dst["dbname"],
    ], check=True, env=dst_env)

    # 2. create the empty destination database
    subprocess.run([
        "createdb",
        "-h", dst_host,
        "-p", str(dst_port),
        "-U", dst["user"],
        dst["dbname"],
    ], check=True, env=dst_env)

    # 3. copy source database into destination
    dump_cmd = [
        "pg_dump",
        "-h", src_host,
        "-p", str(src_port),
        "-U", src["user"],
        src["dbname"],
    ]
    psql_cmd = [
        "psql",
        "-h", dst_host,
        "-p", str(dst_port),
        "-U", dst["user"],
        dst["dbname"],
    ]
    dump_proc = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, env=src_env)
    psql_proc = subprocess.Popen(psql_cmd, stdin=dump_proc.stdout, env=dst_env)
    psql_proc.communicate()
    dump_proc.wait()

    # 4. remove large column contents
    subprocess.run([
        "psql",
        "-h", dst_host,
        "-p", str(dst_port),
        "-U", dst["user"],
        dst["dbname"],
        "-c",
        "UPDATE html_doc_cache SET content = NULL;",
    ], check=True, env=dst_env)
    subprocess.run([
        "psql",
        "-h", dst_host,
        "-p", str(dst_port),
        "-U", dst["user"],
        dst["dbname"],
        "-c",
        "delete from filings where form not like 'D%14A';",
    ], check=True, env=dst_env)

    # 5. dump the sanitized database
    with open(args.output, "wb") as out:
        subprocess.run([
            "pg_dump",
            "--no-owner",
            "--no-privileges",
            "-h", dst_host,
            "-p", str(dst_port),
            "-U", dst["user"],
            dst["dbname"],
        ], check=True, stdout=out, env=dst_env)

    # 6. drop the temporary database
    subprocess.run([
        "dropdb",
        "-h", dst_host,
        "-p", str(dst_port),
        "-U", dst["user"],
        dst["dbname"],
    ], check=True, env=dst_env)


if __name__ == "__main__":
    main()
