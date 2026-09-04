(function() {
    if (window.pluginSystem) {
        window.pluginSystem.registerPlugin({
            name: 'tvcat_show_in_telegram',
            type: 'heropage-action',
            displayName: 'Mostrar en Telegram',
            getHeroButtons: function(itemData) {
                var buttons = [];
                if (itemData && itemData.telegram_link) {
                    buttons.push({
                        id: 'btn-telegram',
                        icon: '<img src="/plugin-static/tvcat_show_in_telegram/plugin.png" style="width:100%;height:100%;object-fit:contain;" onerror="pluginIconFallback(this,\'\uD83D\uDD17\',20)">',
                        tooltip: 'Abrir en Telegram',
                        label: '',
                        action: function() {
                            window.open(itemData.telegram_link, '_blank');
                        }
                    });
                }
                return buttons;
            }
        });
    }
})();
