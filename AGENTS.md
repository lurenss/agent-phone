# agent-phone

TypeScript on Bun. Read README.md for the Android CLI contract.

- The calling agent decides which action serves the user's request, including actions with an external effect. Observe the result after each input.
- Route every operation through the configured walkie-porkie client. Keep the transport in src/walkie.ts and the command vocabulary in src/cli.ts.
- Pass arguments as an array. Send an input once. If the response is lost, observe the phone before making another decision.
- Keep functional tests isolated from real phones, credentials and accounts. Run bun run check before committing.
