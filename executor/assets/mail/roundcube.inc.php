<?php
// Flowline team mail — Roundcube overrides (mounted at /var/roundcube/config/, included after the env-generated config).
// Test environment: plain IMAP/SMTP to greenmail on flownet, no TLS.
$config['imap_host'] = 'mail:3143';
$config['smtp_host'] = 'mail:3025';
$config['smtp_user'] = '%u';
$config['smtp_pass'] = '%p';
$config['imap_conn_options'] = null;
$config['smtp_conn_options'] = null;
$config['username_domain'] = 'northwind.local';   // typing "pm" logs in as pm@northwind.local
$config['product_name'] = 'Northwind Mail';
$config['support_url'] = '';
$config['skin'] = 'elastic';
$config['dark_mode_support'] = false;   // NB: Elastic's meta.json forces this back to true; the desks get light mode
                                         // from Chromium's prefers-color-scheme instead (GTK_THEME=Greybird in mail.sh)
$config['plugins'] = ['archive', 'zipdownload', 'flowline_autologin'];
// Sessions: stay logged in on the desks (the pinned Chromium window must survive the whole day)
$config['session_lifetime'] = 20160;     // minutes (14 days)
$config['ip_check'] = false;
$config['x_frame_options'] = false;
$config['login_rate_limit'] = 0;
// Compose: plain-text editor, reply below, no HTML
$config['htmleditor'] = 0;
$config['compose_mode'] = 'plain';
$config['reply_mode'] = 0;
$config['draft_autosave'] = 0;
$config['mime_param_folding'] = 0;       // attachment names stay readable to imaplib
$config['check_all_folders'] = false;
$config['refresh_interval'] = 30;        // new mail shows up within 30 s
$config['layout'] = 'list';              // no preview pane clutter: list only, a message opens full-width
$config['mail_pagesize'] = 50;
$config['date_format'] = 'Y-m-d';
$config['timezone'] = 'America/Chicago';
$config['max_message_size'] = '20M';
