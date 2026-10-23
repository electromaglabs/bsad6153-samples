"""A minimal, safe tool-using chatbot loop (Week 5 reference).

    python examples/tool_use_example.py "When did my data last sync successfully?"

What it shows, and what your own chatbot must keep doing:
  * The model never touches the database. It can only ask for a TOOL, a Python function
    you wrote, which runs a fixed, parameterized query as the read-only role.
  * Tool inputs are validated in code before anything runs.
  * Every step is printed as a trace (tool, arguments, rows, tokens, cost) so you can
    read what happened, not just the final answer.
  * Hard limits in code: max steps, max response length, row caps.

It uses sync_runs, the table every project has from Week 3. Copy the pattern for your own
tools (3-5 of them) and replace the question with your golden questions.

Using OpenAI instead? The idea is the same ("function calling"): describe each tool with a
JSON schema, run the function yourself when the model asks, and send the result back.
Follow OpenAI's current function-calling documentation for the exact code.
"""

import json
import os
import sys

import anthropic
import psycopg
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5-5"
MAX_STEPS = 6            # the loop stops here, whatever the model wants
MAX_TOKENS = 4000        # cap on each response (part of your spending limits)
MAX_ROWS = 20            # cap on rows any tool may return
# Prices per million tokens, used only to print a cost estimate. Check the provider's
# current pricing page; these change.
PRICE_INPUT_PER_MTOK = 4.00
PRICE_OUTPUT_PER_MTOK = 20.00

SYSTEM_PROMPT = (
    "You answer questions about this project's data-sync history. Answer only from tool "
    "results. If the tools return nothing relevant, say you don't know. End every answer "
    "with a 'Sources:' line naming the tools you used and how many records they returned."
)

TOOLS = [
    {
        "name": "get_recent_sync_runs",
        "description": (
            "Returns the most recent data-sync runs, newest first: run_id, started_at, "
            "finished_at, status (success, partial, or failed), records fetched, inserted, "
            "and updated. Use it for questions about data freshness or sync failures."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": f"How many runs to return, from 1 to {MAX_ROWS}.",
                },
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
        "strict": True,  # the model's arguments must match the schema exactly
    }
]


def get_recent_sync_runs(limit):
    """The tool itself: validated input, fixed SQL, read-only connection, capped rows."""
    if not isinstance(limit, int) or not 1 <= limit <= MAX_ROWS:
        raise ValueError(f"limit must be an integer from 1 to {MAX_ROWS}")
    url = os.environ.get("APP_DATABASE_URL")
    if not url:
        raise RuntimeError("APP_DATABASE_URL is not set")
    with psycopg.connect(url, connect_timeout=10) as conn:
        cursor = conn.execute(
            "select run_id, started_at, finished_at, status, records_fetched, "
            "records_inserted, records_updated from sync_runs "
            "order by started_at desc limit %s",
            (limit,),
        )
        columns = [c.name for c in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


TOOL_FUNCTIONS = {"get_recent_sync_runs": get_recent_sync_runs}


def run_tool(name, arguments):
    """Run one tool call and return (result_text, row_count, is_error)."""
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return f"Unknown tool: {name}", 0, True
    try:
        rows = function(**arguments)
        return json.dumps(rows, default=str), len(rows), False
    except (ValueError, TypeError) as error:
        return f"Invalid input: {error}", 0, True
    except (RuntimeError, psycopg.Error):
        # Don't pass raw database errors to the model; they can reveal internals.
        return "The database is unavailable right now.", 0, True


def ask(question):
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    messages = [{"role": "user", "content": question}]
    total_cost = 0.0

    for step in range(1, MAX_STEPS + 1):
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
            # Effort trades thoroughness for cost; "low" suits chat. You'll tune it in Week 7.
            output_config={"effort": "low"},
            # If a safety classifier wrongly declines a request, retry it on a suitable model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        cost = (response.usage.input_tokens * PRICE_INPUT_PER_MTOK
                + response.usage.output_tokens * PRICE_OUTPUT_PER_MTOK) / 1_000_000
        total_cost += cost
        print(f"[step {step}] stop={response.stop_reason} tokens in/out="
              f"{response.usage.input_tokens}/{response.usage.output_tokens} cost~${cost:.4f}")

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            return f"The request was declined (category: {category}).", total_cost
        if response.stop_reason == "max_tokens":
            return "The answer was cut off by the length limit. Try a narrower question.", total_cost
        if response.stop_reason != "tool_use":
            text = "".join(block.text for block in response.content if block.type == "text")
            return text, total_cost

        # The model asked for one or more tools: run each, then send all results back together.
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            output, row_count, is_error = run_tool(block.name, block.input)
            print(f"         tool {block.name}({json.dumps(block.input)}) -> "
                  f"{'ERROR: ' + output if is_error else f'{row_count} rows'}")
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})

    return f"Stopped after {MAX_STEPS} steps without a final answer.", total_cost


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "When did my data last sync successfully?"
    try:
        answer, cost = ask(question)
    except anthropic.AuthenticationError:
        sys.exit("Invalid or missing ANTHROPIC_API_KEY. Check your .env file.")
    except anthropic.RateLimitError:
        sys.exit("Rate limited. Wait a minute and try again.")
    except anthropic.BadRequestError as error:
        sys.exit(f"The request was rejected: {error.message}")
    except anthropic.APIStatusError as error:
        sys.exit(f"API error {error.status_code}. Try again later.")
    except anthropic.APIConnectionError:
        sys.exit("Couldn't reach the API. Check your internet connection.")
    print("\n" + answer)
    print(f"\nEstimated cost of this question: ${cost:.4f}")
