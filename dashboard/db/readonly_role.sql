-- Read-only login used by the deployed backend (Vercel env var DATABASE_URL). Run as the database owner after
-- load.mjs. Replace CHANGE_ME with a long random password; never commit the real one.
CREATE ROLE dashboard_ro LOGIN PASSWORD 'CHANGE_ME' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE neondb TO dashboard_ro;
GRANT USAGE ON SCHEMA public TO dashboard_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dashboard_ro;
