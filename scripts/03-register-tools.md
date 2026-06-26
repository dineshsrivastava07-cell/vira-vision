# Step 3 — Register VIRA Vision tools in Open WebUI

One-time UI step (stored in Open WebUI's database).

## 1. Create admin account
Open `http://localhost:3000` and create the first account (becomes admin).

## 2. Confirm the model
**Admin Panel > Settings > Models** — confirm `gemma4:12b` is listed.

## 3. Register the tool server
**Admin Panel > Settings > Tools > Add**
- URL: `http://vira-tools:8000` *(container-to-container; same Docker network)*
- Save. Open WebUI fetches `/openapi.json` and registers all endpoints as tools:
  `answer_question`, `sudhhar_stores`, `sudhhar_inventory_analysis`,
  `governed_search`, `detect_anomalies`, `open_liveboard`, `trigger_workflow`

> Registering from an external browser? Use the public IP and ensure
> `ALLOWED_ORIGINS` in `.env` includes that origin.

## 4. Enable Native function calling
**Workspace > Models > gemma4:12b > Advanced Params > Function Calling = Native**

## 5. Add system prompt
**Workspace > Models > gemma4:12b > System Prompt:**

```
You are VIRA Vision, a retail analytics assistant.

Tool routing:
- Sales / ATV / UPT / inventory / region / zone questions  -> answer_question
- 100 Ka Sudhaar / underperforming / weak stores           -> sudhhar_stores
- Inventory value locked / capital in stock                -> sudhhar_inventory_analysis
- Official governed metrics                                -> governed_search
- Outlier / anomaly detection                              -> detect_anomalies
- Persistent shareable dashboard                           -> open_liveboard
- Trigger alert / ticket / report                          -> trigger_workflow

Always show the SQL or search query you ran. Never invent numbers.
```

## 6. Verify
Ask: *"top 10 stores by net sales last month"*
Expected: model calls `answer_question`, returns table + chart.
