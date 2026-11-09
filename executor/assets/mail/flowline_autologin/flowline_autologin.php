<?php
/**
 * flowline_autologin — opening http://webmail/?_task=mail&_fl_user=pm logs that person in (password: the shared test
 * password) when there is no session yet. Lets the pinned desk windows come up logged in without driving the form, and
 * re-logs in on a reload if the session was ever lost. Test environment only.
 */
class flowline_autologin extends rcube_plugin
{
    public $task = '';   // every task: the request that needs us is the first (unauthenticated) one

    function init()
    {
        $this->add_hook('startup', [$this, 'startup']);
        $this->add_hook('authenticate', [$this, 'authenticate']);
    }

    function startup($args)
    {
        if (empty($_SESSION['user_id']) && !empty($_GET['_fl_user'])) {
            $args['task']   = 'login';
            $args['action'] = 'login';
        }
        return $args;
    }

    function authenticate($args)
    {
        if (!empty($_GET['_fl_user'])) {
            $user = preg_replace('/[^a-z0-9._-]/i', '', $_GET['_fl_user']);
            if (strpos($user, '@') === false) {
                $user .= '@' . (getenv('FLOWLINE_MAIL_DOMAIN') ?: 'northwind.local');
            }
            $args['user']        = $user;
            $args['pass']        = getenv('FLOWLINE_MAIL_PASSWORD') ?: 'flowline';
            $args['host']        = 'mail:3143';
            $args['cookiecheck'] = false;
            $args['valid']       = true;
        }
        return $args;
    }
}
