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
                        icon: '<img src="/plugin-static/tvcat_show_in_telegram/plugin.png" style="width:20px;height:20px;object-fit:cover;" onerror="pluginIconFallback(this,\'\uD83D\uDD17\',20)">',
                        label: 'Abrir en<br>Telegram',
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
