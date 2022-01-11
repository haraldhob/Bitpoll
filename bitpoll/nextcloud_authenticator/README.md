# Nextcloud OAuth Integration

We use the Django allauth library as the base tool to authenticate users against the Nextcloud OAuth API.

The problem is, that the library is currently missing an adequate Nextcloud module, meaning we had
to write our own implementation. This Nextcloud_authenticator app is a backend for the allauth
library, implementing the communication with the Nextcloud OAuth API.

## Authentication Process

The process for authenticating a new user works as follows:
1. The user sends a request to the Bitpoll application.
2. The Django authentication middleware is called. Our custom `AuthRequiredMiddleware`
   (middleware.py) detects that the current user is not authenticated (we don't have a valid
   authentication token in storage).
3. The user is redirected to the Nextcloud OAuth Authentication page. This is a subpage of the
   Nextcloud application. We configured the Nextcloud in advance to accept these kinds of requests
   and redirect authenticated users together with their new authentication token to a subpage of the
   Bitpoll application.
4. After being redirected to the Bitpoll application, the user presents its newly acquired access
   token to our application. Using this token, we first verify that this token is correct and then
   use it to acquire the users account data from the Nextcloud instance. This is done via another
   nextcloud OAuth API endpoint. The user does not notice this. 
5. After receiving the additional user information, we start the user authentication process. This
   is mostly handled via the django allauth library. All modifications to this process are
   documented below.

The whole process of authenticating the user against the Nextcloud instance if skipped, if the user
already has a valid login token stored in its Bitpoll user account.

## Nextcloud Setup

To enable authentication using the Nextcloud OAuth API, we first have to setup the API endpoint. All
information for the setup is also supplied in the comment above the `SOCIALACCOUNT_PROVIDERS`
setting in `settings_local.py`. Here is an exact copy of the instructions:

1. Log in with admin permissions and navigate to settings/admin/security.
2. Add a new OAuth 2.0 client at the bottom of the page (Nextcloud Version 20)
    - "Name": This can be any name.
    - "Redirection URI": This has to be the following URI (fill in the base domain):
        -> 'https://<bitpoll_domain>/accounts/nextcloud_auth/login/callback/' <-
3. Copy the "Client Identification" and paste it into the "client_id" field.
4. Copy the "Secret" and paste it into the "secret" field. 

## Code Documentation

### adapter.py

The account adapter is used by Django allauth to interact with user accounts. It is here only
subclassed to disable the creation of new user accounts. This would otherwise automatically be done
via the allauth library for unregistered users. As we don't want new users to register themselves,
this is disabled. (New users are only created via the API endpoints exposed to the User Provisioning
Script)

### apps.py

This is required to register signals on app loading. This is a Django related procedure. Without
this, the signal handlers are ignored.

### middleware.py

The `AuthRequiredMiddleware` is a type of `AuthenticationMiddleware` that is not directly required
for user authentication. However, it is used to force authentication against the Nextcloud OAuth API
for currently unauthenticated users. This results in an automatic redirect of unauthenticated users
to the Nextcloud login page. 

Paths that do not trigger this automatic redirect are "api" (for API calls that authenticate with
another method -> User Provisioning Script), "admin" (for local admin access, in case the Nextcloud
OAuth API doesn't work) and the login url. This login url does not cause redirects, because users
are first redirected back from the Nextcloud instance to this URL to be authenticated. Redirecting
these users would cause an infinite redirection loop.

### provider.py

The `CustomNextcloudProvider`-provider is required for the Django allauth provider plugin system. It
uses existing functionality from the builtin `NextcloudProvider`. To handle all user data later in
the authentication process, we do not pre-select fields from the data that the Nextcloud OAuth API
sends us. This would otherwise be done in the `extract_common_fields`-method.

### signals.py

We use the `user_signed_up` and `social_account_updated` signals as a hacky trigger for group
processing. The Django allauth login process does not offer a possibility to add this custom
behavior, so we assign the correct groups to the users in a post-processing step, after
authentication.

Every time the user data that comes from the Nextcloud OAuth API during authentication changes, the
`user_login_callback` signal handler is executed. We string-match every group that the user is a
member of in the Nextcloud with the groups that exist for Bitpoll users. The result of this method
is, that the group memberships of users are synced between the Nextcloud and the Bitpoll ecosystems.
This synchronization is triggered at most every time the corresponding user authenticates.

Additionally, a setting `ADMIN_GROUPS` (set e.g. in settings.py) determines the Nextcloud groups
that are only contain users with admin access rights. If the currently authenticating user is a
member of such a group, then we also reward its social account (the user account of the Django
allauth library) the `is_superuser` flag that marks admin users and the `is_staff` flag that grants
access to the admin pages.

### urls.py

This only adds the default authentication url patterns, required for the Django allauth
authentication process.

### views.py

The code here is the heart of our custom login process. We both configure the existing
`NextcloudAdapter` and implement a custom version of the `get_user_info` method that is used to
extract the required user login information from the API response JSON dict.

The API response that comes from the Nextcloud OAuth API is a bit weird. The "username" or login is
called "id" and the "displayname" is a combination of the first and last name. The name splitting
applied here is only a legacy feature and won't be needed of a user account already exists for the
authenticating user. User groups are supplied as a list of group names, which is nice, but can't be
handled by Django allauth.
