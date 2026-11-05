-- =====================================================
-- LIMPEZA ÚNICA (2026-11-05) — correr uma vez no SQL Editor do Supabase.
-- 1) Planos de pintura já todo entregues passam a "Pronto" (a app passou a
--    fazê-lo sozinha a partir de hoje; isto acerta os antigos).
-- 2) Apaga 19 planos de carga duplicados de jun–set (mesmo plano com espaço
--    ou "_" no nome). Fica sempre a cópia onde os operadores separaram; o que
--    se apaga fica copiado em historico_alteracoes e pode ser recuperado.
-- =====================================================
begin;

update plans p set status = 'pronto'
 where p.tipo = 'pintura' and p.status <> 'pronto'
   and exists (select 1 from plan_items i where i.plan_id = p.id)
   and not exists (select 1 from plan_items i where i.plan_id = p.id and not coalesce(i.entregue, false));

delete from plan_items where plan_id::text in (
  '9f73b0c9-75c7-405d-b03a-02e8fe07a7c3', -- LATERAL_W37
  '97ead9da-493b-4d97-b42e-b004fd33a1cd', -- DESTAK W37
  '48878172-0d5e-4e88-be81-72c5bff90602', -- ENERNEL W37
  '562a44dc-8594-4106-ae89-c70dd0a5238f', -- SONERES W37
  'd10a2615-d405-03cf-03bf-39332e29c4ab', -- CONDURIL W36
  'a6faf144-06a3-4d79-84b8-4efce5fbcf1b', -- GREENVOLT_W36
  'e7b0a484-d159-4059-a41f-d5a09fc8413a', -- VENTURE_W36_1
  '26d23c8c-aee6-4cd3-8a15-31d7fe927c13', -- VENTURE_W36_2
  'a4a09037-7cfe-46df-bf85-24b4ddf2f614', -- SOTECNO W35
  '1a1b43b5-194f-4170-9d7f-a21bef784f97', -- PLURALUZ_W35
  '6569e5cb-6779-4bc2-8d30-14ab9da8f5e5', -- VOLT E MEIO W35
  '7df1aec0-f86a-46c7-b953-8f030beb4ba5', -- LAPERLUZ_W35
  'd86dea4b-27eb-44ec-a4e8-07fefe79ade1', -- PEIXOTO W34
  '765b9510-eb75-49d8-afec-1b5e1af5cea6', -- QBEIRAS W34
  'aaba705c-7d01-42cd-8dfa-60e8471679e4', -- NELAS W34
  '4eb562e1-f034-4f96-8f9a-2be79ed65453', -- ELECTROFER W32
  '0b6e2cfb-f3a4-4aa5-adef-5352ec1b64d4', -- COBELBA W28
  '58819112-0b45-4caf-8566-91c4a05d47b6', -- DE_W25_1 (vazio)
  'c20a0833-b0a1-4e99-8f11-3677f32f7bb2'  -- PORVELOX W24
);

delete from plans where id::text in (
  '9f73b0c9-75c7-405d-b03a-02e8fe07a7c3', '97ead9da-493b-4d97-b42e-b004fd33a1cd',
  '48878172-0d5e-4e88-be81-72c5bff90602', '562a44dc-8594-4106-ae89-c70dd0a5238f',
  'd10a2615-d405-03cf-03bf-39332e29c4ab', 'a6faf144-06a3-4d79-84b8-4efce5fbcf1b',
  'e7b0a484-d159-4059-a41f-d5a09fc8413a', '26d23c8c-aee6-4cd3-8a15-31d7fe927c13',
  'a4a09037-7cfe-46df-bf85-24b4ddf2f614', '1a1b43b5-194f-4170-9d7f-a21bef784f97',
  '6569e5cb-6779-4bc2-8d30-14ab9da8f5e5', '7df1aec0-f86a-46c7-b953-8f030beb4ba5',
  'd86dea4b-27eb-44ec-a4e8-07fefe79ade1', '765b9510-eb75-49d8-afec-1b5e1af5cea6',
  'aaba705c-7d01-42cd-8dfa-60e8471679e4', '4eb562e1-f034-4f96-8f9a-2be79ed65453',
  '0b6e2cfb-f3a4-4aa5-adef-5352ec1b64d4', '58819112-0b45-4caf-8566-91c4a05d47b6',
  'c20a0833-b0a1-4e99-8f11-3677f32f7bb2'
)
returning nome, data;

commit;
