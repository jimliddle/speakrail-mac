# Local Memory

Memory is optional and intended for one person using one local voice session.
It adds no model, embeddings, database or network service.

## Start

```sh
./mac/start-voice-prototype --memory-dir
```

The default directory is `~/Library/Application Support/Speakrail/memory`.
For another location, pass a directory after `--memory-dir`. It must be outside
the repository. Open the full URL printed in Terminal. Its access fragment is
exchanged for an HttpOnly, SameSite cookie and removed from the address bar.
The key changes when the launcher restarts; reopen the new link then.
Do not share that link or the launch log.

Memory mode requires the loopback host `127.0.0.1`, local inference endpoints
and conversation tools. It cannot be combined with `--conversation-only`,
`--test` or preview-only mode. The ordinary launch command still works without
memory and does not create or read memory files.

## Files and Editor

Open **Settings > Memory**:

- `persona.md` supplies speaking style and identity preferences alongside the
  conversation controller's instructions. Defaults are neutral, not a personal
  profile or a copy of the maintainer's settings.
- `profile.md` holds your name and standing preferences. Edit it directly for
  facts you want available at the start of each session.
- `memories/<id>.md` contains individual notes with update times and source labels.

Stop the voice session before editing files; leave the server running. Start a
new session to pick up persona or profile changes. The editor checks revisions
to avoid overwriting a change made elsewhere. You can inspect a pending voice
change and confirm or discard it while the session is active.

Files are UTF-8 Markdown, not compressed archives. They have owner-only file
permissions (600); memory directories use 700. They are not encrypted. Anyone
with access to your OS account can read them. This is not a multiuser system.

## Speaking to Astra

1. "Remember that the telescope project needs approval before Friday."
2. "Confirm memory change."
3. "Check your memories about the telescope project."
4. "Update that memory: approval is needed by Thursday instead."
5. "Confirm memory change."
6. "Forget the memory about the telescope project."
7. "Confirm memory change."

Saving, updating and deleting start as proposals. The spoken confirmation or
the editor's Confirm change button commits them. Proposals expire after two
minutes and are discarded on Stop or chat reset. Only one proposal is pending
at a time. A bare "yes" is not enough to commit it.

These explicit phrases are handled after the speech controller accepts the
turn, including when it prepared a speculative reply. Ordinary conversation
still uses the model. Other phrasings depend on its tool selection and may need
rephrasing. A memory result is evidence of what was saved, not proof that the
statement is true or still current.

Recall uses lexical matching and returns up to three excerpts of 1,800
characters each. It includes record IDs, dates and a matching count. An exact
ID or `profile` query reads a full record. An empty query returns recent notes.
A missed match does not establish that no relevant memory exists; inspect the
editor or use different words. "That memory" must identify one recalled record;
ambiguous deletion asks for clarification.

Persona and profile files allow 2,000 characters each. Notes allow 4,000, with
up to 200 notes. Keep exact dates, amounts and qualifications when shortening
them. Lists, to-dos and counters remain session-only.

## Privacy and Removal

The standalone memory profile rejects web-search, Claude Bridge and hosted
frontier tools, and disables the weather tool. Its model, recognition and
speech endpoints must be on loopback. The memory code makes no external calls.
This is not an OS network sandbox: the existing browser page can still request
Google Fonts, and independently running local services have their own settings.

No transcript or recording is automatically added to memory. The native
launcher keeps recording off. If you separately enable session logs, those
files can contain recalled text. Deleting a note removes its memory file, not
backups, logs or an active conversation's context. Start a fresh session after
deletion when that distinction matters. Avoid storing passwords or access keys.

The editor and voice endpoints require the launch cookie, reject foreign
origins and unexpected Host headers, and allow one voice session at a time.
These checks protect against unauthorised browser requests, not another program
running under your own OS account.

To disable memory, stop the stack and start it without `--memory-dir`. To remove
the saved data, stop the stack and delete your chosen memory directory. No model
weights, other app settings or sessions need to be removed.
