import os

_FRONTEND_BASE_URL = os.getenv('FRONTEND_BASE_URL', '')
_LOGO_URL = f'{_FRONTEND_BASE_URL}/logo.png'


def get_connection_request_email(recipient_name: str, from_name: str, from_id: str) -> tuple[str, str, str]:
    first_name = recipient_name.split()[0]
    profile_url = f'{_FRONTEND_BASE_URL}/dads/{from_id}'
    subject = 'You Have a New Connection Request'
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Connection Request - Next Level Dads</title>
</head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;">

  <table role="presentation" cellpadding="0" cellspacing="0"
         border="0" width="100%">
    <tr>
      <td style="padding:32px 16px;">

        <table role="presentation" cellpadding="0" cellspacing="0"
               border="0" width="100%"
               style="max-width:480px;background-color:#f7f1e6;
                      border:1px solid #D4C9B8;
                      border-radius:10px;overflow:hidden;">

          <!-- Gold header -->
          <tr>
            <td align="center"
                style="background-color:#AD8225;padding:20px 16px;">
              <p style="margin:0;color:#ffffff;font-size:20px;
                        line-height:26px;font-weight:700;">
                Connection Request 👋
              </p>
            </td>
          </tr>

          <!-- Centered content -->
          <tr>
            <td align="center"
                style="padding:48px 28px 0;text-align:center;">

              <p style="margin:0 0 40px;color:#243035;
                        font-size:20px;line-height:28px;">
                Hi {first_name},
              </p>

              <p style="margin:0 0 20px;color:#243035;
                        font-size:20px;line-height:30px;">
                <strong>{from_name}</strong> wants to connect with you
                on Next Level Dads!
              </p>

              <table role="presentation" cellpadding="0"
                     cellspacing="0" border="0" style="margin:0 auto;">
                <tr>
                  <td align="center"
                      bgcolor="#AD8225"
                      style="border-radius:7px;">
                    <a href="{profile_url}"
                       style="display:inline-block;padding:14px 32px;
                              color:#ffffff;text-decoration:none;
                              font-size:17px;font-weight:700;
                              line-height:24px;border-radius:7px;">
                      View Profile
                    </a>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Bottom-right logo -->
          <tr>
            <td align="right"
                style="padding:10px 18px 18px;">
              <img src="{_LOGO_URL}"
                   alt="Next Level Dads"
                   width="90"
                   style="display:block;width:90px;
                          max-width:100%;height:auto;border:0;">
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""
    text = (
        f'Hi {first_name},\n\n'
        f'{from_name} wants to connect with you on Next Level Dads!\n\n'
        f'View their profile: {profile_url}\n'
    )
    return subject, html, text


def get_connection_accepted_email(recipient_name: str, by_name: str, by_id: str) -> tuple[str, str, str]:
    first_name = recipient_name.split()[0]
    profile_url = f'{_FRONTEND_BASE_URL}/dads/{by_id}'
    subject = 'You Have a New Connection'
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>New Connection - Next Level Dads</title>
</head>
<body style="margin:0;padding:0;font-family:Arial,Helvetica,sans-serif;">

  <table role="presentation" cellpadding="0" cellspacing="0"
         border="0" width="100%">
    <tr>
      <td style="padding:32px 16px;">

        <table role="presentation" cellpadding="0" cellspacing="0"
               border="0" width="100%"
               style="max-width:480px;background-color:#f7f1e6;
                      border:1px solid #D4C9B8;
                      border-radius:10px;overflow:hidden;">

          <!-- Gold header -->
          <tr>
            <td align="center"
                style="background-color:#AD8225;padding:20px 16px;">
              <p style="margin:0;color:#ffffff;font-size:20px;
                        line-height:26px;font-weight:700;">
                New Connection 🤝
              </p>
            </td>
          </tr>

          <!-- Centered content -->
          <tr>
            <td align="center"
                style="padding:48px 28px 0;text-align:center;">

              <p style="margin:0 0 40px;color:#243035;
                        font-size:20px;line-height:28px;">
                Hi {first_name},
              </p>

              <p style="margin:0 0 20px;color:#243035;
                        font-size:20px;line-height:30px;">
                <strong>{by_name}</strong> accepted your connection request
                on Next Level Dads!
              </p>

              <table role="presentation" cellpadding="0"
                     cellspacing="0" border="0" style="margin:0 auto;">
                <tr>
                  <td align="center"
                      bgcolor="#AD8225"
                      style="border-radius:7px;">
                    <a href="{profile_url}"
                       style="display:inline-block;padding:14px 32px;
                              color:#ffffff;text-decoration:none;
                              font-size:17px;font-weight:700;
                              line-height:24px;border-radius:7px;">
                      View Profile
                    </a>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Bottom-right logo -->
          <tr>
            <td align="right"
                style="padding:10px 18px 18px;">
              <img src="{_LOGO_URL}"
                   alt="Next Level Dads"
                   width="90"
                   style="display:block;width:90px;
                          max-width:100%;height:auto;border:0;">
            </td>
          </tr>

        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""
    text = (
        f'Hi {first_name},\n\n'
        f'{by_name} accepted your connection request on Next Level Dads!\n\n'
        f'View their profile: {profile_url}\n'
    )
    return subject, html, text
