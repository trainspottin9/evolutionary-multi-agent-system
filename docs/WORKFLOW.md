# Task lifecycle and review workflow

The v3 workflow carries forward v2's independently implemented review model and borrows high-level product ideas from [Multica](https://github.com/multica-ai/multica): an issue-like task, an inbox for human decisions, a review gate, and a readable execution log. No Multica code, UI components, runtime integrations, or database schema are included.

## Execution and review are separate

`Engine.run` continues to report technical execution status (`success`, `failed`, or `blocked`) and objective evaluator metrics. A successful task submitted through the local Web UI creates a separate review with `pending` status. The reviewer can move it to `accepted` or `changes_requested`; requesting changes requires feedback. A failed or blocked run does not create a pending review. Human acceptance never changes the original technical result or an official evaluation score.

```text
Web task → planner/bids/execution → success → pending review
                                      ├─ accepted
                                      └─ changes_requested → revising → linked new Web task
```

The new run receives the original goal plus the review feedback. Its result and review are stored under a new task ID, with `revision_of` pointing to the previous task. Previous outputs and traces remain available. Each review transition is appended to `review_events` so a later state does not erase the decision history. If the revision run fails, its review is marked `execution_failed` and the original returns to `changes_requested`, allowing another attempt.

## Local Web routes

| Route | Purpose |
| --- | --- |
| `GET /api/overview` | Recent root tasks, review states, direct group chat |
| `GET /api/inbox` | Pending reviews and in-memory jobs waiting on a human |
| `GET /api/trace/{task_id}` | Task tree, messages, approvals, actions, review and review events |
| `POST /api/reviews/{task_id}` | Accept or request changes with feedback |
| `POST /api/revisions` | Start one linked rerun from a review requesting changes |

Writes require the page's per-server token, JSON content type, localhost host check, and matching browser origin. The API key remains on the host. The Web server is intended for local use only; it does not provide remote user authentication or durable queued jobs across server restarts. Review records and task traces are durable in SQLite, while an approval question in flight is held in server memory and expires after ten minutes.

## Verification

The tests cover pending review creation after a successful Web task, inbox visibility, requested changes, a linked rerun, acceptance of the rerun, decision history, and rejection of a second decision on the same pending review. They also run the inherited planning, delegation, memory, tool and evaluation tests. These tests use a scripted provider and temporary state. No user-visible demonstration task was inserted into the v3 workspace during development.

Course submission still needs real team GitHub history and official test-set results. The review gate is useful for human oversight, but it is not a substitute for those requirements.
