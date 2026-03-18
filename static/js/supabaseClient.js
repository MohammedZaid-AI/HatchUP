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
            console.error("Supabase client configuration is missing.", {
                hasSupabaseGlobal: !!window.supabase,
                hasUrl: !!config.url,
                hasAnonKey: !!config.anonKey,
                origin: window.location.origin,
            });
            return null;
        }

        client = window.supabase.createClient(config.url, config.anonKey, {
            auth: {
                persistSession: true,
                autoRefreshToken: true,
                detectSessionInUrl: true,
            },
        });
        console.log("Supabase client initialized for", window.location.origin);
        return client;
    }

    window.getSupabaseClient = function () {
        return createSupabaseClient();
    };
})();
