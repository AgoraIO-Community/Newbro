# Public Onboarding and Ownership

Newbro's first hosted public path is self-signup gated by a shared access code
and owner-scoped after signup.

The public runtime still keeps Communication Brain, Execution Brain, shared
blackboard, connectors, and detached executor nodes as separate boundaries. The
ownership layer only decides which browser user may access a runtime object.

## Accounts and Sessions

The hosted service configures one fixed signup code with
`NEWBRO_SIGNUP_INVITE_CODE`. A browser user signs up with an email address and
that code. The code is only an access gate; every successful signup creates a
new lightweight user record, even if the email was used before.

Operators may still create legacy invite codes with:

```bash
newbro invite create
newbro invite create friend-code --email user@example.com
```

Signup or legacy invite redemption creates an HttpOnly `newbro_session`
browser cookie. Browser routes for sessions, conversations, drafts, personas,
executor nodes, and voice preparation require that cookie. Logout clears the
cookie, drops the current browser shell session state, and returns the browser
to the signup gate.

The bootstrap route creates or resumes the user's default runtime session and
syncs the user's persisted Bros/personas into that session. It does not create a
default Bro. If the user has no personas, Home stays in the empty workspace
state until the first-run connect flow observes a user-owned executor node that
has connected successfully at least once.

## Owned Objects

The public auth store owns these bindings:

- browser session token to user
- runtime session id to user
- persona id to user
- executor node id to user

User B must not list, read, mutate, bind, reveal credentials for, or use User
A's owned objects. Cross-user misses return `404` so object existence is not
confirmed.

Detached executor nodes still authenticate to `/api/executors/control` with
their node id and node token. Browser ownership controls who can create, reveal,
rotate, bind, and delete those nodes.

## Voice and Connectors

The hosted service owns OpenAI and Agora credentials. Browser voice starts from
Bro Detail through same-origin connector routes under `/api/connectors/...`.

Bro Detail is node-gated for runtime Bros. If the active Bro has no
`executor_node_id`, or its bound node has never connected successfully, the
detail route shows an inline setup panel instead of the voice bar, draft
controls, task controls, or normal workspace. The first-run Home setup creates a
private executor node and shows a copyable `newbro executor run ...` command,
but it does not create the Bro persona until the frontend refreshes state and
observes `last_connected_at` on that node. API persona creation and node binding
also reject user-owned nodes that have not connected successfully once.

A created node is not yet usable. A usable node is one with a durable
`last_connected_at`, meaning the executor websocket registered successfully at
least once. A usable node may still be currently disconnected. In that case Bro
Detail remains visible, but browser voice/talk controls are blocked with a
warning and a command-copy path until the node reconnects. The frontend keeps
the current page/session state visible if a usable node disconnects during an
active voice session.

Agora ConvoAI and STT browser prepare/start paths are owner-scoped to the
current runtime session. Connector-to-runtime callbacks use the internal
connector token instead of browser cookies.

## Waiting for Execution

Draft confirmation may create a task before the user's bound local executor
node is live. In that case the task stays in `waiting_executor`.

For an already-bound Bro, Bro Detail shows a "Connect Codex to run" state and
can reveal a copyable local node command for the bound node.
