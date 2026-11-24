CREATE USER ragstore_migrator WITH PASSWORD 'migrator';
CREATE USER ragstore_search WITH PASSWORD 'search' NOBYPASSRLS;
CREATE USER ragstore_files WITH PASSWORD 'files' NOBYPASSRLS;
CREATE USER ragstore_worker WITH PASSWORD 'worker' NOBYPASSRLS;
CREATE DATABASE ragstore OWNER ragstore_migrator;
\connect ragstore
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
GRANT CONNECT ON DATABASE ragstore TO ragstore_search, ragstore_files, ragstore_worker;
GRANT CREATE ON DATABASE ragstore TO ragstore_migrator;
