-- Atomic store (R5): the idempotency guarantee "file_hash seen <=> fully stored"
-- only holds if the invoice, its children, its events, and any supersede-mark
-- commit together. supabase-py's REST layer can't do multi-statement
-- transactions, so we do it in a single Postgres function (one implicit tx).
--
-- Called from the Supabase store path as: rpc('store_invoice', {...}).

create or replace function store_invoice(
    p_invoice         jsonb,
    p_line_items      jsonb default '[]'::jsonb,
    p_tax_lines       jsonb default '[]'::jsonb,
    p_field_conf      jsonb default '[]'::jsonb,
    p_events          jsonb default '[]'::jsonb,
    p_mark_superseded uuid  default null
) returns uuid
language plpgsql
as $$
declare
    v_id uuid;
    rec  jsonb;
begin
    insert into invoices (
        id, vendor_id, invoice_number, invoice_date, due_date, doc_type, currency,
        subtotal, tax_total, discount, shipping, total,
        base_currency, base_total, fx_rate, fx_date,
        category, status, version, supersedes_id, credit_of_id,
        file_hash, source, source_ref, confidence_overall, is_invoice
    ) values (
        coalesce((p_invoice->>'id')::uuid, gen_random_uuid()),
        (p_invoice->>'vendor_id')::uuid,
        p_invoice->>'invoice_number',
        (p_invoice->>'invoice_date')::date,
        (p_invoice->>'due_date')::date,
        coalesce(p_invoice->>'doc_type', 'invoice'),
        p_invoice->>'currency',
        (p_invoice->>'subtotal')::numeric,
        (p_invoice->>'tax_total')::numeric,
        (p_invoice->>'discount')::numeric,
        (p_invoice->>'shipping')::numeric,
        (p_invoice->>'total')::numeric,
        p_invoice->>'base_currency',
        (p_invoice->>'base_total')::numeric,
        (p_invoice->>'fx_rate')::numeric,
        (p_invoice->>'fx_date')::date,
        p_invoice->>'category',
        coalesce(p_invoice->>'status', 'received'),
        coalesce((p_invoice->>'version')::int, 1),
        (p_invoice->>'supersedes_id')::uuid,
        (p_invoice->>'credit_of_id')::uuid,
        p_invoice->>'file_hash',
        p_invoice->>'source',
        p_invoice->>'source_ref',
        (p_invoice->>'confidence_overall')::numeric,
        coalesce((p_invoice->>'is_invoice')::boolean, true)
    )
    returning id into v_id;

    for rec in select value from jsonb_array_elements(coalesce(p_line_items, '[]'::jsonb)) loop
        insert into line_items (invoice_id, description, quantity, unit_price, amount)
        values (v_id, rec->>'description', (rec->>'quantity')::numeric,
                (rec->>'unit_price')::numeric, (rec->>'amount')::numeric);
    end loop;

    for rec in select value from jsonb_array_elements(coalesce(p_tax_lines, '[]'::jsonb)) loop
        insert into tax_lines (invoice_id, label, rate, amount)
        values (v_id, rec->>'label', (rec->>'rate')::numeric, (rec->>'amount')::numeric);
    end loop;

    for rec in select value from jsonb_array_elements(coalesce(p_field_conf, '[]'::jsonb)) loop
        insert into field_conf (invoice_id, field, confidence)
        values (v_id, rec->>'field', (rec->>'confidence')::numeric)
        on conflict (invoice_id, field) do update set confidence = excluded.confidence;
    end loop;

    for rec in select value from jsonb_array_elements(coalesce(p_events, '[]'::jsonb)) loop
        -- honour the emit-time ts so the timeline reflects real step durations
        insert into events (invoice_id, type, detail, ts)
        values (v_id, rec->>'type', coalesce(rec->'detail', '{}'::jsonb),
                coalesce((rec->>'ts')::timestamptz, now()));
    end loop;

    if p_mark_superseded is not null then
        update invoices set status = 'superseded', updated_at = now()
        where id = p_mark_superseded;
    end if;

    return v_id;
end;
$$;
