# Sign-in

This guide tells you how to set up Clerk sign-in and how to run a server for more than one family.

## Clerk sign-in

Frecklebubby uses [Clerk](https://clerk.com) for sign-in with Google or GitHub. Clerk is also the OAuth provider for
Claude connectors. A free Clerk development instance is enough for a family.

In the Clerk dashboard:

1. Make an application. Turn on **Google** and **GitHub** under **SSO connections > Add connection > For all
   users**. Development instances need no Google or GitHub setup.
2. **User authentication > Access mode**: select **Invite-only**. Invite each family member under **Users**.
   (Also invite them in Frecklebubby: **Settings > Family > Invite**.)
3. **Sessions > Customize session token**: add the email claim. Frecklebubby needs it to know who signed in:

   ```json
   {
     "email": "{{user.primary_email_address}}",
     "name": "{{user.full_name}}"
   }
   ```

4. **OAuth applications > Add application** (for Claude and other MCP clients): scopes `openid email profile`,
   redirect URI `<BASE_URL>/auth/callback`, entered exactly, with no `/` at the end. Copy the client ID and the
   client secret. Clerk shows the secret only once.
5. Copy these values to `.env`:

   | `.env` | Where in Clerk |
   |---|---|
   | `CLERK_PUBLISHABLE_KEY` | **API keys > Publishable key** (`pk_...`) |
   | `CLERK_DOMAIN` | The instance host, for example `your-instance.clerk.accounts.dev` (no `https://`) |
   | `CLERK_OAUTH_CLIENT_ID`, `CLERK_OAUTH_CLIENT_SECRET` | The OAuth application from step 4 |

Optional: put a comma list of emails in `ALLOWED_EMAILS`. Then other emails cannot sign in, even with an invite.

The server does not start in Clerk mode if a value is missing. The log names the missing value.

> Tested with a real Clerk development instance (0.3.1): sign-in and the email claim. A carer invite and a
> refused email are not yet tested with a real account.

### A server for more than one family (invite only)

Put your email in `OPERATOR_EMAILS` (comma list). Then the server is invite only and you are an operator:

- **Settings > Server access** lets you invite an email. That person can sign in and start one family. The app
  sends no email; tell the person yourself. You can remove an invite that is not used yet.
- A family invites its own carers, as before. They get in without a change from you.
- An operator sees family names, member emails and dates. An operator cannot read, change, block or delete the
  data of another family.
- A family owner can delete the family in **Settings > Delete data**. A user can delete the account there.
  After that the person needs a new invite.
- `ALLOWED_EMAILS` stays optional: with `OPERATOR_EMAILS` set, it is a fixed list of more emails that can sign in.

Protection for a public server: requests to the AI model, uploads and wrong tokens have rate limits, and the model
takes one request at a time (the others wait in order). The settings are in `.env.example`. Behind a Cloudflare
Tunnel set `BEHIND_CLOUDFLARE=true`.
