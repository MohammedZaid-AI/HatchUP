(function () {
    let client = null;

    function getSupabaseConfig() {
        return window.HATCHUP_SUPABASE || {};
    }

    function createSupabaseClient() {
        if (client) {
            return client;
        }

        const config = getSupabaseConfig();
        if (!window.supabase || !config.url || !config.anonKey) {
            return null;
        }

        client = window.supabase.createClient(config.url, config.anonKey, {
            auth: {
                persistSession: true,
                autoRefreshToken: true,
                detectSessionInUrl: true,
            },
        });
        return client;
    }

    window.getSupabaseClient = function () {
        return createSupabaseClient();
    };
})();
