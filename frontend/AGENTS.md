<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# mycelium frontend

Read `README.md` here for the layout and the test layers, and the repo's `docs/ARCHITECTURE.md` §10 for what the app is.
The rules that a test enforces are in `src/lib/__tests__/designlaws.unit.test.ts`: the network only in `lib/api`, components
only on `lib/queries`, barrels only, fixtures lazy, colour from the tokens.
