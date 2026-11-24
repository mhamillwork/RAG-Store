"""Row-level security policies and least-privilege grants.

Application roles do not own these tables and do not have BYPASSRLS. The
migration role owns the tables and is the only role that bypasses row-level
security. Identity is transaction-local (``set_config(..., true)``). Policies
also check ``current_user`` before granting worker privileges, so an API role
cannot become a worker by setting a session variable.

Row-level security is defense in depth against forgotten predicates. It is not
a control against an attacker who can already execute arbitrary SQL as an
application role.
"""

RLS_SQL = r"""
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ragstore_search')
     OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ragstore_files')
     OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ragstore_worker') THEN
    RAISE EXCEPTION
      'Database roles ragstore_search, ragstore_files, and ragstore_worker must exist before migration. See docs/postgresql-setup.md.';
  END IF;
END $$;

CREATE OR REPLACE FUNCTION ragstore.actor_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION ragstore.actor_role() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(current_setting('app.role', true), '')
$$;

CREATE OR REPLACE FUNCTION ragstore.is_worker() RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT current_user = 'ragstore_worker'
$$;

CREATE OR REPLACE FUNCTION ragstore.user_count() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ragstore, public AS $$
  SELECT count(*) FROM ragstore.users
$$;

REVOKE ALL ON FUNCTION ragstore.actor_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION ragstore.actor_role() FROM PUBLIC;
REVOKE ALL ON FUNCTION ragstore.is_worker() FROM PUBLIC;
REVOKE ALL ON FUNCTION ragstore.user_count() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ragstore.actor_id() TO ragstore_search, ragstore_files, ragstore_worker;
GRANT EXECUTE ON FUNCTION ragstore.actor_role() TO ragstore_search, ragstore_files, ragstore_worker;
GRANT EXECUTE ON FUNCTION ragstore.is_worker() TO ragstore_search, ragstore_files, ragstore_worker;
GRANT EXECUTE ON FUNCTION ragstore.user_count() TO ragstore_files, ragstore_worker;

CREATE OR REPLACE FUNCTION ragstore.lookup_user(p_id uuid)
RETURNS TABLE (
  id uuid, username text, display_name text, role text, is_active boolean,
  storage_key text, password_hash text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ragstore, public AS $$
  SELECT id, username, display_name, role, is_active, storage_key, password_hash
  FROM ragstore.users WHERE id = p_id
$$;

CREATE OR REPLACE FUNCTION ragstore.lookup_login(p_username text)
RETURNS TABLE (
  id uuid, username text, display_name text, role text, is_active boolean,
  storage_key text, password_hash text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ragstore, public AS $$
  SELECT id, username, display_name, role, is_active, storage_key, password_hash
  FROM ragstore.users WHERE username = lower(p_username)
$$;

CREATE OR REPLACE FUNCTION ragstore.lookup_api_key(p_hash text)
RETURNS TABLE (
  credential_id uuid, user_id uuid, username text, display_name text, role text,
  is_active boolean, storage_key text, expires_at timestamptz, revoked_at timestamptz
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ragstore, public AS $$
  SELECT c.id, u.id, u.username, u.display_name, u.role, u.is_active, u.storage_key, c.expires_at, c.revoked_at
  FROM ragstore.api_credentials c
  JOIN ragstore.users u ON u.id = c.user_id
  WHERE c.key_hash = p_hash
$$;

REVOKE ALL ON FUNCTION ragstore.lookup_user(uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION ragstore.lookup_login(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION ragstore.lookup_api_key(text) FROM PUBLIC;
CREATE OR REPLACE FUNCTION ragstore.lookup_refresh(p_hash text)
RETURNS TABLE (
  session_id uuid, id uuid, username text, display_name text, role text,
  is_active boolean, storage_key text
)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ragstore, public AS $$
  SELECT s.id, u.id, u.username, u.display_name, u.role, u.is_active, u.storage_key
  FROM ragstore.user_sessions s
  JOIN ragstore.users u ON u.id = s.user_id
  WHERE s.token_hash = p_hash AND s.revoked_at IS NULL AND s.expires_at > now()
$$;

REVOKE ALL ON FUNCTION ragstore.lookup_refresh(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ragstore.lookup_user(uuid) TO ragstore_search, ragstore_files;
GRANT EXECUTE ON FUNCTION ragstore.lookup_login(text) TO ragstore_search, ragstore_files;
GRANT EXECUTE ON FUNCTION ragstore.lookup_api_key(text) TO ragstore_search, ragstore_files;
GRANT EXECUTE ON FUNCTION ragstore.lookup_refresh(text) TO ragstore_search, ragstore_files;

CREATE OR REPLACE FUNCTION ragstore.protect_user_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.storage_key IS DISTINCT FROM OLD.storage_key THEN
    RAISE EXCEPTION 'user identity is immutable';
  END IF;
  IF NEW.role IS DISTINCT FROM OLD.role AND ragstore.actor_role() IS DISTINCT FROM 'admin' THEN
    RAISE EXCEPTION 'only an administrator can change roles';
  END IF;
  IF NEW.is_active IS DISTINCT FROM OLD.is_active AND ragstore.actor_role() IS DISTINCT FROM 'admin' THEN
    RAISE EXCEPTION 'only an administrator can change account status';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS users_protect_identity ON ragstore.users;
CREATE TRIGGER users_protect_identity
  BEFORE UPDATE ON ragstore.users
  FOR EACH ROW EXECUTE FUNCTION ragstore.protect_user_identity();

CREATE OR REPLACE FUNCTION ragstore.enforce_collection_link() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  col_scope text;
  col_owner uuid;
BEGIN
  SELECT scope, owner_id INTO col_scope, col_owner
  FROM ragstore.collections WHERE id = NEW.collection_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'collection % does not exist', NEW.collection_id;
  END IF;
  IF NEW.scope IS DISTINCT FROM col_scope THEN
    RAISE EXCEPTION 'scope does not match the collection';
  END IF;
  IF col_scope = 'local' AND NEW.owner_id IS DISTINCT FROM col_owner THEN
    RAISE EXCEPTION 'local ownership does not match the collection';
  END IF;
  IF col_scope = 'global' AND col_owner IS NOT NULL THEN
    RAISE EXCEPTION 'a global collection cannot have an owner';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS documents_scope ON ragstore.documents;
CREATE TRIGGER documents_scope
  BEFORE INSERT OR UPDATE ON ragstore.documents
  FOR EACH ROW EXECUTE FUNCTION ragstore.enforce_collection_link();

DROP TRIGGER IF EXISTS folders_scope ON ragstore.folders;
CREATE TRIGGER folders_scope
  BEFORE INSERT OR UPDATE ON ragstore.folders
  FOR EACH ROW EXECUTE FUNCTION ragstore.enforce_collection_link();

CREATE OR REPLACE FUNCTION ragstore.enforce_chunk_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  doc_scope text;
  doc_owner uuid;
  doc_collection uuid;
BEGIN
  SELECT scope, owner_id, collection_id INTO doc_scope, doc_owner, doc_collection
  FROM ragstore.documents WHERE id = NEW.document_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'chunk document % does not exist', NEW.document_id;
  END IF;
  IF NEW.scope IS DISTINCT FROM doc_scope
     OR NEW.owner_id IS DISTINCT FROM doc_owner
     OR NEW.collection_id IS DISTINCT FROM doc_collection THEN
    RAISE EXCEPTION 'chunk ownership does not match its document';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS chunks_scope ON ragstore.document_chunks;
CREATE TRIGGER chunks_scope
  BEFORE INSERT OR UPDATE ON ragstore.document_chunks
  FOR EACH ROW EXECUTE FUNCTION ragstore.enforce_chunk_scope();

CREATE OR REPLACE FUNCTION ragstore.can_read_scope(row_scope text, row_owner uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT
    ragstore.is_worker()
    OR (
      row_scope = 'global'
      AND ragstore.actor_id() IS NOT NULL
      AND ragstore.actor_role() IN ('admin', 'user', 'service')
    )
    OR (
      row_scope = 'local'
      AND row_owner = ragstore.actor_id()
      AND ragstore.actor_role() IN ('admin', 'user')
    )
$$;

CREATE OR REPLACE FUNCTION ragstore.can_write_scope(row_scope text, row_owner uuid) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT
    ragstore.is_worker()
    OR (row_scope = 'global' AND ragstore.actor_role() = 'admin')
    OR (
      row_scope = 'local'
      AND row_owner = ragstore.actor_id()
      AND ragstore.actor_role() IN ('admin', 'user')
    )
$$;

REVOKE ALL ON FUNCTION ragstore.can_read_scope(text, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION ragstore.can_write_scope(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ragstore.can_read_scope(text, uuid) TO ragstore_search, ragstore_files, ragstore_worker;
GRANT EXECUTE ON FUNCTION ragstore.can_write_scope(text, uuid) TO ragstore_search, ragstore_files, ragstore_worker;

-- users
ALTER TABLE ragstore.users ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS users_select ON ragstore.users;
CREATE POLICY users_select ON ragstore.users FOR SELECT
  USING (ragstore.is_worker() OR id = ragstore.actor_id() OR ragstore.actor_role() = 'admin');
DROP POLICY IF EXISTS users_insert ON ragstore.users;
CREATE POLICY users_insert ON ragstore.users FOR INSERT
  WITH CHECK (ragstore.actor_role() = 'admin' OR ragstore.user_count() = 0);
DROP POLICY IF EXISTS users_update ON ragstore.users;
CREATE POLICY users_update ON ragstore.users FOR UPDATE
  USING (id = ragstore.actor_id() OR ragstore.actor_role() = 'admin')
  WITH CHECK (id = ragstore.actor_id() OR ragstore.actor_role() = 'admin');

-- sessions and credentials are visible only to the owner, an administrator, or the worker role
ALTER TABLE ragstore.user_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_sessions_all ON ragstore.user_sessions;
CREATE POLICY user_sessions_all ON ragstore.user_sessions FOR ALL
  USING (ragstore.is_worker() OR user_id = ragstore.actor_id() OR ragstore.actor_role() = 'admin')
  WITH CHECK (ragstore.is_worker() OR user_id = ragstore.actor_id() OR ragstore.actor_role() = 'admin');

ALTER TABLE ragstore.api_credentials ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS api_credentials_all ON ragstore.api_credentials;
CREATE POLICY api_credentials_all ON ragstore.api_credentials FOR ALL
  USING (ragstore.is_worker() OR user_id = ragstore.actor_id() OR ragstore.actor_role() = 'admin')
  WITH CHECK (ragstore.is_worker() OR user_id = ragstore.actor_id() OR ragstore.actor_role() = 'admin');

ALTER TABLE ragstore.user_quotas ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS user_quotas_select ON ragstore.user_quotas;
CREATE POLICY user_quotas_select ON ragstore.user_quotas FOR SELECT
  USING (ragstore.is_worker() OR user_id = ragstore.actor_id() OR ragstore.actor_role() = 'admin');
DROP POLICY IF EXISTS user_quotas_write ON ragstore.user_quotas;
CREATE POLICY user_quotas_write ON ragstore.user_quotas FOR ALL
  USING (ragstore.is_worker() OR ragstore.actor_role() = 'admin' OR user_id = ragstore.actor_id())
  WITH CHECK (ragstore.is_worker() OR ragstore.actor_role() = 'admin' OR user_id = ragstore.actor_id());

ALTER TABLE ragstore.collections ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS collections_select ON ragstore.collections;
CREATE POLICY collections_select ON ragstore.collections FOR SELECT
  USING (ragstore.can_read_scope(scope, owner_id));
DROP POLICY IF EXISTS collections_write ON ragstore.collections;
CREATE POLICY collections_write ON ragstore.collections FOR ALL
  USING (ragstore.can_write_scope(scope, owner_id))
  WITH CHECK (
    ragstore.is_worker()
    OR (scope = 'global' AND owner_id IS NULL AND ragstore.actor_role() = 'admin')
    OR (scope = 'local' AND owner_id = ragstore.actor_id() AND ragstore.actor_role() IN ('admin', 'user'))
  );

ALTER TABLE ragstore.folders ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS folders_all ON ragstore.folders;
CREATE POLICY folders_all ON ragstore.folders FOR ALL
  USING (ragstore.can_read_scope(scope, owner_id))
  WITH CHECK (ragstore.can_write_scope(scope, owner_id));

ALTER TABLE ragstore.documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS documents_select ON ragstore.documents;
CREATE POLICY documents_select ON ragstore.documents FOR SELECT
  USING (ragstore.can_read_scope(scope, owner_id));
DROP POLICY IF EXISTS documents_write ON ragstore.documents;
CREATE POLICY documents_write ON ragstore.documents FOR ALL
  USING (ragstore.can_write_scope(scope, owner_id))
  WITH CHECK (ragstore.can_write_scope(scope, owner_id));

ALTER TABLE ragstore.document_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_versions_all ON ragstore.document_versions;
CREATE POLICY document_versions_all ON ragstore.document_versions FOR ALL
  USING (
    ragstore.is_worker()
    OR EXISTS (
      SELECT 1 FROM ragstore.documents d
      WHERE d.id = document_id AND ragstore.can_read_scope(d.scope, d.owner_id)
    )
  )
  WITH CHECK (
    ragstore.is_worker()
    OR EXISTS (
      SELECT 1 FROM ragstore.documents d
      WHERE d.id = document_id AND ragstore.can_write_scope(d.scope, d.owner_id)
    )
  );

ALTER TABLE ragstore.docling_documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS docling_documents_all ON ragstore.docling_documents;
CREATE POLICY docling_documents_all ON ragstore.docling_documents FOR ALL
  USING (
    EXISTS (
      SELECT 1 FROM ragstore.document_versions v
      JOIN ragstore.documents d ON d.id = v.document_id
      WHERE v.id = document_version_id AND ragstore.can_read_scope(d.scope, d.owner_id)
    )
    OR ragstore.is_worker()
  )
  WITH CHECK (ragstore.is_worker());

ALTER TABLE ragstore.docling_document_segments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS docling_segments_all ON ragstore.docling_document_segments;
CREATE POLICY docling_segments_all ON ragstore.docling_document_segments FOR ALL
  USING (
    ragstore.is_worker()
    OR EXISTS (SELECT 1 FROM ragstore.docling_documents dd WHERE dd.id = docling_document_id)
  )
  WITH CHECK (ragstore.is_worker());

ALTER TABLE ragstore.document_tables ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_tables_all ON ragstore.document_tables;
CREATE POLICY document_tables_all ON ragstore.document_tables FOR ALL
  USING (
    ragstore.is_worker()
    OR EXISTS (
      SELECT 1 FROM ragstore.document_versions v
      JOIN ragstore.documents d ON d.id = v.document_id
      WHERE v.id = document_version_id AND ragstore.can_read_scope(d.scope, d.owner_id)
    )
  )
  WITH CHECK (ragstore.is_worker());

ALTER TABLE ragstore.document_assets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_assets_all ON ragstore.document_assets;
CREATE POLICY document_assets_all ON ragstore.document_assets FOR ALL
  USING (ragstore.can_read_scope(scope, owner_id))
  WITH CHECK (ragstore.is_worker() OR ragstore.can_write_scope(scope, owner_id));

ALTER TABLE ragstore.document_chunks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS document_chunks_all ON ragstore.document_chunks;
CREATE POLICY document_chunks_all ON ragstore.document_chunks FOR ALL
  USING (ragstore.can_read_scope(scope, owner_id))
  WITH CHECK (ragstore.is_worker() OR ragstore.can_write_scope(scope, owner_id));

ALTER TABLE ragstore.embedding_models ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS embedding_models_select ON ragstore.embedding_models;
CREATE POLICY embedding_models_select ON ragstore.embedding_models FOR SELECT
  USING (ragstore.actor_id() IS NOT NULL OR ragstore.is_worker());
DROP POLICY IF EXISTS embedding_models_write ON ragstore.embedding_models;
CREATE POLICY embedding_models_write ON ragstore.embedding_models FOR ALL
  USING (ragstore.is_worker())
  WITH CHECK (ragstore.is_worker());

ALTER TABLE ragstore.chunk_embeddings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS chunk_embeddings_all ON ragstore.chunk_embeddings;
CREATE POLICY chunk_embeddings_all ON ragstore.chunk_embeddings FOR ALL
  USING (
    ragstore.is_worker()
    OR EXISTS (
      SELECT 1 FROM ragstore.document_chunks c
      WHERE c.id = chunk_id AND ragstore.can_read_scope(c.scope, c.owner_id)
    )
  )
  WITH CHECK (ragstore.is_worker());

ALTER TABLE ragstore.ingestion_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ingestion_jobs_select ON ragstore.ingestion_jobs;
CREATE POLICY ingestion_jobs_select ON ragstore.ingestion_jobs FOR SELECT
  USING (ragstore.can_read_scope(scope, owner_id));
DROP POLICY IF EXISTS ingestion_jobs_write ON ragstore.ingestion_jobs;
CREATE POLICY ingestion_jobs_write ON ragstore.ingestion_jobs FOR ALL
  USING (ragstore.can_write_scope(scope, owner_id) OR ragstore.is_worker())
  WITH CHECK (ragstore.can_write_scope(scope, owner_id) OR ragstore.is_worker());

ALTER TABLE ragstore.ingestion_attempts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ingestion_attempts_all ON ragstore.ingestion_attempts;
CREATE POLICY ingestion_attempts_all ON ragstore.ingestion_attempts FOR ALL
  USING (
    ragstore.is_worker()
    OR EXISTS (SELECT 1 FROM ragstore.ingestion_jobs j WHERE j.id = job_id)
  )
  WITH CHECK (ragstore.is_worker());

ALTER TABLE ragstore.upload_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS upload_sessions_all ON ragstore.upload_sessions;
CREATE POLICY upload_sessions_all ON ragstore.upload_sessions FOR ALL
  USING (ragstore.is_worker() OR user_id = ragstore.actor_id() OR (scope = 'global' AND ragstore.actor_role() = 'admin'))
  WITH CHECK (ragstore.is_worker() OR user_id = ragstore.actor_id());

ALTER TABLE ragstore.audit_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS audit_events_select ON ragstore.audit_events;
CREATE POLICY audit_events_select ON ragstore.audit_events FOR SELECT
  USING (ragstore.actor_role() = 'admin' OR ragstore.is_worker());
DROP POLICY IF EXISTS audit_events_insert ON ragstore.audit_events;
CREATE POLICY audit_events_insert ON ragstore.audit_events FOR INSERT
  WITH CHECK (
    ragstore.actor_id() IS NOT NULL
    OR ragstore.is_worker()
    OR current_user IN ('ragstore_files', 'ragstore_search')
  );

ALTER TABLE ragstore.rate_buckets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rate_buckets_all ON ragstore.rate_buckets;
CREATE POLICY rate_buckets_all ON ragstore.rate_buckets FOR ALL
  USING (ragstore.is_worker() OR user_id = ragstore.actor_id() OR ragstore.actor_role() = 'admin')
  WITH CHECK (ragstore.is_worker() OR user_id = ragstore.actor_id() OR ragstore.actor_role() = 'admin');

ALTER TABLE ragstore.dropbox_observations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS dropbox_observations_all ON ragstore.dropbox_observations;
CREATE POLICY dropbox_observations_all ON ragstore.dropbox_observations FOR ALL
  USING (current_user IN ('ragstore_worker', 'ragstore_files'))
  WITH CHECK (current_user = 'ragstore_worker');

ALTER TABLE ragstore.distributed_leases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS distributed_leases_all ON ragstore.distributed_leases;
CREATE POLICY distributed_leases_all ON ragstore.distributed_leases FOR ALL
  USING (current_user IN ('ragstore_worker', 'ragstore_files', 'ragstore_search'))
  WITH CHECK (current_user = 'ragstore_worker');

ALTER TABLE ragstore.worker_heartbeats ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS worker_heartbeats_all ON ragstore.worker_heartbeats;
CREATE POLICY worker_heartbeats_all ON ragstore.worker_heartbeats FOR ALL
  USING (current_user IN ('ragstore_worker', 'ragstore_files', 'ragstore_search'))
  WITH CHECK (current_user = 'ragstore_worker');

ALTER TABLE ragstore.inference_permits ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS inference_permits_all ON ragstore.inference_permits;
CREATE POLICY inference_permits_all ON ragstore.inference_permits FOR ALL
  USING (current_user IN ('ragstore_worker', 'ragstore_files', 'ragstore_search'))
  WITH CHECK (current_user IN ('ragstore_worker', 'ragstore_search'));

GRANT USAGE ON SCHEMA ragstore TO ragstore_search, ragstore_files, ragstore_worker;

GRANT SELECT ON
  ragstore.users,
  ragstore.api_credentials,
  ragstore.collections,
  ragstore.folders,
  ragstore.documents,
  ragstore.document_versions,
  ragstore.docling_documents,
  ragstore.docling_document_segments,
  ragstore.document_tables,
  ragstore.document_assets,
  ragstore.document_chunks,
  ragstore.chunk_embeddings,
  ragstore.embedding_models,
  ragstore.ingestion_jobs,
  ragstore.user_quotas,
  ragstore.worker_heartbeats,
  ragstore.distributed_leases
TO ragstore_search;
GRANT SELECT, INSERT, UPDATE, DELETE ON ragstore.rate_buckets TO ragstore_search;
GRANT SELECT, INSERT, UPDATE, DELETE ON ragstore.inference_permits TO ragstore_search;
GRANT INSERT ON ragstore.audit_events TO ragstore_search;
GRANT UPDATE (last_used_at) ON ragstore.api_credentials TO ragstore_search;

GRANT SELECT, INSERT, UPDATE ON ragstore.users TO ragstore_files;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  ragstore.user_sessions,
  ragstore.api_credentials,
  ragstore.user_quotas,
  ragstore.collections,
  ragstore.folders,
  ragstore.documents,
  ragstore.document_versions,
  ragstore.upload_sessions,
  ragstore.ingestion_jobs,
  ragstore.rate_buckets
TO ragstore_files;
GRANT UPDATE, DELETE ON ragstore.document_chunks TO ragstore_files;
GRANT DELETE ON ragstore.documents TO ragstore_files;
GRANT SELECT ON
  ragstore.docling_documents,
  ragstore.docling_document_segments,
  ragstore.document_tables,
  ragstore.document_assets,
  ragstore.document_chunks,
  ragstore.chunk_embeddings,
  ragstore.embedding_models,
  ragstore.ingestion_attempts,
  ragstore.worker_heartbeats,
  ragstore.distributed_leases,
  ragstore.inference_permits,
  ragstore.dropbox_observations,
  ragstore.audit_events
TO ragstore_files;
GRANT INSERT ON ragstore.audit_events TO ragstore_files;
GRANT UPDATE ON ragstore.ingestion_jobs TO ragstore_files;

GRANT SELECT ON ragstore.users TO ragstore_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON
  ragstore.collections,
  ragstore.folders,
  ragstore.documents,
  ragstore.document_versions,
  ragstore.docling_documents,
  ragstore.docling_document_segments,
  ragstore.document_tables,
  ragstore.document_assets,
  ragstore.document_chunks,
  ragstore.chunk_embeddings,
  ragstore.embedding_models,
  ragstore.ingestion_jobs,
  ragstore.ingestion_attempts,
  ragstore.distributed_leases,
  ragstore.inference_permits,
  ragstore.worker_heartbeats,
  ragstore.user_quotas,
  ragstore.upload_sessions,
  ragstore.dropbox_observations,
  ragstore.rate_buckets,
  ragstore.audit_events
TO ragstore_worker;
"""
