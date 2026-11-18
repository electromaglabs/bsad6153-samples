-- db/roles.sql: who may do what in your database (Week 2, extended in Week 6).
--
-- NEVER PUT A PASSWORD IN THIS FILE. It is committed to GitHub.
-- Create each role here without a password, then set the password separately
-- in the Supabase SQL editor (and nowhere in your repository):
--
--     alter role app_reader with password '...long random password...';
--
-- Then put the role's connection string in .env as APP_DATABASE_URL.
--
-- Safe to run more than once: the role is created only if it doesn't exist yet,
-- and repeating a GRANT changes nothing. Run the whole file again whenever you add a table.

-- ---------------------------------------------------------------------------
-- Week 3: app_reader, the read-only role for the golden-question checker,
-- website (Milestone 4), and chatbot (Milestone 5).
-- ---------------------------------------------------------------------------
do $$
begin
    if not exists (select from pg_roles where rolname = 'app_reader') then
        create role app_reader login;
    end if;
end
$$;

-- Lets the role see that the tables in the public schema exist. Without it, every query fails.
grant usage on schema public to app_reader;

-- Read-only access to the data tables. No INSERT, UPDATE, DELETE, or TRUNCATE is granted,
-- so any attempt to change data fails with "permission denied".
grant select on applicants, applications, service_requests, rfp_documents to app_reader;

-- Row Level Security (RLS) is switched on for these tables in Supabase. With RLS on, a role
-- sees only the rows a policy allows, and with no policy it silently sees zero rows (no error).
-- These policies let app_reader read every row. We keep RLS on rather than turning it off:
-- Supabase's built-in anon and authenticated roles have no policy, so they still see nothing
-- if the Data API is ever switched back on. The sync connects as postgres, which skips RLS.
-- "drop policy if exists" first keeps this file safe to run again.
drop policy if exists app_reader_select on applicants;
create policy app_reader_select on applicants for select to app_reader using (true);
drop policy if exists app_reader_select on applications;
create policy app_reader_select on applications for select to app_reader using (true);
drop policy if exists app_reader_select on service_requests;
create policy app_reader_select on service_requests for select to app_reader using (true);
drop policy if exists app_reader_select on rfp_documents;
create policy app_reader_select on rfp_documents for select to app_reader using (true);

-- sync_runs (Part C): app_reader may read the run log; only the sync (as postgres) writes to it.
grant select on sync_runs to app_reader;
drop policy if exists app_reader_select on sync_runs;
create policy app_reader_select on sync_runs for select to app_reader using (true);

-- Stops a runaway query (for example, one a chatbot wrote) from tying up the database.
alter role app_reader set statement_timeout = '15s';

-- ---------------------------------------------------------------------------
-- Week 6: the agent's own role (see the Week 6 page for the exact grants).
-- ---------------------------------------------------------------------------
-- create role agent_writer login;
-- grant usage on schema public to agent_writer;
-- grant select on <your data tables>, sync_runs, agent_runs, agent_proposals to agent_writer;
-- grant insert on agent_runs, agent_proposals to agent_writer;
-- grant update on agent_runs to agent_writer;
--
-- Week 6: the one write your website may do, which covers only the review columns.
-- grant select on agent_runs, agent_proposals to app_reader;
-- grant update (status, reviewed_at, reviewer_note) on agent_proposals to app_reader;
