# Sign-in

This guide tells you how to set up Clerk sign-in and how to run a server for more than one family.

## Clerk sign-in

Frecklebubby uses [Clerk](https://clerk.com) for sign-in with Google or GitHub. Clerk is also the OAuth provider for
Claude connectors. A free Clerk development instance is enough for a family. For more people, see
[A Clerk production instance](#a-clerk-production-instance).

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

### A Clerk production instance

A development instance is for a family. Before you invite other people, move to a production instance. A
development instance has a low user limit, shows a "Development mode" label, and uses Clerk's shared test
credentials for Google and GitHub.

The server needs no change other than four values in `.env`. It keeps working on the development instance until
step 6.

1. In the Clerk dashboard, open the instance menu at the top and select **Create production instance**. Select the
   option to copy the development settings. Give your root domain, for example `example.com`, also when the app is
   on a subdomain such as `my.example.com`.
2. Add the 5 CNAME records that Clerk shows to your DNS (`clerk`, `accounts` and 3 mail records). With Cloudflare,
   set each record to **DNS only**. With the proxy on, Clerk cannot make its certificates.
3. Give each sign-in provider your own credentials (**SSO connections > the provider > Use custom credentials**).
   Clerk shows the redirect address for the provider, `https://clerk.example.com/v1/oauth_callback`.
   - Google: in the Google Cloud console, make an OAuth client of the type **Web application** with that redirect
     address. Set the consent screen to **In production**. Google asks for a home page, a privacy policy and a
     developer email. To show your app name on the Google screen, prove that you own the domain in Google Search
     Console (one TXT record).
   - GitHub: **Settings > Developer settings > OAuth Apps > New OAuth App**, with that address as the callback URL.
   - Turn off each provider that has no credentials.
4. Do steps 3 and 4 of the list above again in the production instance: the session token claims and the OAuth
   application. Make sure that the instance selector shows **Production**.
5. Change the four values in `.env`. `BASE_URL` does not change.

   | `.env` | Value |
   |---|---|
   | `CLERK_DOMAIN` | `clerk.example.com` |
   | `CLERK_PUBLISHABLE_KEY` | The production key, which starts with `pk_live_` |
   | `CLERK_OAUTH_CLIENT_ID`, `CLERK_OAUTH_CLIENT_SECRET` | The new OAuth application |

6. Start the app again: `docker compose up -d app`.

Effects of the move:

- Each person must sign in one time again. Clerk does not copy the users. Frecklebubby finds each person by email,
  so the families and the logs stay connected. A person must use the same email as before.
- Each Claude connector (or other MCP client) must be connected again.
- Access tokens from **Settings** continue to work.

> Tested with a real Clerk production instance (0.8.10): sign-in with Google, and a Claude connector.

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
takes `LLM_PARALLEL` requests at a time (4 with the bundled model server; the others wait in order). The settings are in `.env.example`. Behind a Cloudflare
Tunnel set `BEHIND_CLOUDFLARE=true`.
