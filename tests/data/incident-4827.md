# INC-4827  (SEV-2, OPEN)
Service: payments-api   Opened: 2026-06-12T09:21:00Z
5xx rate crossed 7% shortly after dep-1191. Suspected cause: downstream
timeout raised from 5s to 30s, so failing calls now pile up instead of
shedding fast. Owner: rao.
