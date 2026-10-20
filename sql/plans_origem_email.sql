-- Data do email de que cada plano foi feito (auditoria 2026-10-20).
-- A rotina compara-a com os emails seguintes do mesmo fio: se chegou um PDF
-- corrigido ou uma mudança de data/hora, aplica-a ao plano em vez de o saltar.
alter table plans add column if not exists origem_email_em timestamptz;
