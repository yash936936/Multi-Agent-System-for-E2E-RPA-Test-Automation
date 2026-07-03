# Login Flow

Given: app is launched
Given: user is logged out

The user clicks on the Login button, top-right.
The user enters a username into the Username field.
The user enters a password into the Password field.
The user clicks on the Submit button.

The user should see the Dashboard visible after logging in.

## Data requirements

The test needs a valid username and password. It should also include an
edge case unicode name and a boundary max length password to check input
handling.
