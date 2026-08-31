/**
 * TVCat - Módulo de Visualización de Kiosko Premium (Revistas y Cómics)
 */

var Kiosko = {
    itemId: null,
    title: "",
    currentPage: 1,
    totalPages: 1,
    zoomLevel: 100,
    isTransitioning: false,
    isFullscreen: false,
    saveProgressTimeout: null,
    preloadedImages: {},

    // Inicializar y abrir el visor
    openViewer: function(itemId) {
        if (!itemId) return;
        var self = this;
        this.itemId = itemId;
        this.currentPage = 1;
        this.totalPages = 1;
        this.zoomLevel = 100;
        this.preloadedImages = {};
        
        var loader = document.getElementById("kiosko-loader");
        var modal = document.getElementById("kiosko-modal");
        var img = document.getElementById("kiosko-page-img");
        
        // Mostrar modal e indicador de carga inicial
        modal.classList.remove("hidden");
        loader.classList.remove("hidden");
        img.src = "";
        
        // 1. Obtener metadatos y progreso desde el backend
        var url = "/api/kiosko/info/" + itemId;
        fetch(url)
            .then(function(response) { return response.json(); })
            .then(function(data) {
                if (!data || !data.ok) {
                    alert(data.detail || "Error al inicializar el cómic.");
                    self.closeViewer();
                    return;
                }
                
                self.title = data.title || "Revista";
                self.totalPages = data.total_pages || 1;
                self.currentPage = data.last_page || 1;
                
                // Actualizar interfaz
                document.getElementById("kiosko-title").textContent = self.title;
                document.getElementById("kiosko-total-pages").textContent = "/ " + self.totalPages;
                document.getElementById("kiosko-page-input").max = self.totalPages;
                
                // Registrar atajos de teclado
                self.registerKeyboardShortcuts();
                
                // Cargar página inicial
                self.loadPage(self.currentPage);
            })
            .catch(function(err) {
                console.error("Error al abrir visor de kiosko:", err);
                alert("No se pudo conectar con el visor de Kiosko. Inténtalo de nuevo.");
                self.closeViewer();
            });
    },

    // Cerrar visor
    closeViewer: function() {
        // Guardar progreso final de inmediato si hay cambios pendientes
        if (this.saveProgressTimeout) {
            clearTimeout(this.saveProgressTimeout);
            this.saveProgressBackend();
        }
        
        // Desregistrar atajos de teclado
        this.unregisterKeyboardShortcuts();
        
        // Ocultar modal
        var modal = document.getElementById("kiosko-modal");
        modal.classList.add("hidden");
        
        // Limpiar fuentes de imagen para liberar memoria RAM del navegador
        document.getElementById("kiosko-page-img").src = "";
        
        this.itemId = null;
        this.preloadedImages = {};
        
        // Si está en pantalla completa, salir
        if (document.fullscreenElement) {
            try { document.exitFullscreen(); } catch(e) {}
        }
    },

    // Cargar una página específica (1-indexed)
    loadPage: function(pageNum) {
        if (pageNum < 1 || pageNum > this.totalPages) return;
        this.currentPage = pageNum;
        
        var img = document.getElementById("kiosko-page-img");
        var loader = document.getElementById("kiosko-loader");
        var pageInput = document.getElementById("kiosko-page-input");
        
        loader.classList.remove("hidden");
        pageInput.value = this.currentPage;
        
        // Determinar URL de la página
        var pageUrl = "/api/kiosko/page/" + this.itemId + "/" + this.currentPage;
        
        // Cargar imagen
        img.src = pageUrl;
        
        // Disparar guardado de progreso de lectura interactivo con debounce (3 segundos)
        this.triggerSaveProgress();
        
        // Precargar páginas contiguas
        this.preloadNeighborPages();
    },

    // Evento de carga de imagen finalizada
    onImageLoad: function() {
        var loader = document.getElementById("kiosko-loader");
        loader.classList.add("hidden");
        this.resetZoom();
    },

    // Páginas siguientes y anteriores
    nextPage: function() {
        if (this.currentPage < this.totalPages) {
            this.loadPage(this.currentPage + 1);
        }
    },

    prevPage: function() {
        if (this.currentPage > 1) {
            this.loadPage(this.currentPage - 1);
        }
    },

    // Control de cambio numérico manual de página
    onPageInputChange: function(val) {
        var page = parseInt(val, 10);
        if (!isNaN(page) && page >= 1 && page <= this.totalPages) {
            this.loadPage(page);
        } else {
            document.getElementById("kiosko-page-input").value = this.currentPage;
        }
    },

    // Ajuste de zoom interactivo
    zoomIn: function() {
        if (this.zoomLevel < 300) {
            this.zoomLevel += 25;
            this.applyZoom();
        }
    },

    zoomOut: function() {
        if (this.zoomLevel > 50) {
            this.zoomLevel -= 25;
            this.applyZoom();
        }
    },

    resetZoom: function() {
        this.zoomLevel = 100;
        this.applyZoom();
    },

    applyZoom: function() {
        var wrapper = document.getElementById("kiosko-page-wrapper");
        var zoomText = document.getElementById("kiosko-zoom-level");
        
        wrapper.style.transform = "scale(" + (this.zoomLevel / 100) + ")";
        zoomText.textContent = this.zoomLevel + "%";
    },

    // Pantalla Completa
    toggleFullscreen: function() {
        var self = this;
        var container = document.getElementById("kiosko-modal");
        
        if (!document.fullscreenElement) {
            container.requestFullscreen()
                .then(function() {
                    self.isFullscreen = true;
                })
                .catch(function(err) {
                    console.error("Error al iniciar Fullscreen:", err);
                });
        } else {
            document.exitFullscreen()
                .then(function() {
                    self.isFullscreen = false;
                });
        }
    },

    // Atajos de Teclado
    registerKeyboardShortcuts: function() {
        var self = this;
        this.keyHandler = function(e) {
            if (self.itemId === null) return;
            
            switch (e.key) {
                case "ArrowRight":
                case "d":
                case "D":
                    self.nextPage();
                    e.preventDefault();
                    break;
                case "ArrowLeft":
                case "a":
                case "A":
                    self.prevPage();
                    e.preventDefault();
                    break;
                case "Escape":
                    self.closeViewer();
                    e.preventDefault();
                    break;
                case "+":
                    self.zoomIn();
                    e.preventDefault();
                    break;
                case "-":
                    self.zoomOut();
                    e.preventDefault();
                    break;
                case "0":
                    self.resetZoom();
                    e.preventDefault();
                    break;
                case "f":
                case "F":
                    self.toggleFullscreen();
                    e.preventDefault();
                    break;
            }
        };
        window.addEventListener("keydown", this.keyHandler);
    },

    unregisterKeyboardShortcuts: function() {
        if (this.keyHandler) {
            window.removeEventListener("keydown", this.keyHandler);
            this.keyHandler = null;
        }
    },

    // Guardado de progreso con debounce inteligente
    triggerSaveProgress: function() {
        var self = this;
        if (this.saveProgressTimeout) {
            clearTimeout(this.saveProgressTimeout);
        }
        this.saveProgressTimeout = setTimeout(function() {
            self.saveProgressBackend();
        }, 3000);
    },

    saveProgressBackend: function() {
        var self = this;
        if (!this.itemId) return;
        
        var payload = {
            item_id: this.itemId,
            page_num: this.currentPage
        };
        
        fetch("/api/kiosko/progress", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        })
        .then(function() {
            console.log("[KIOSKO PROGRESS] Progreso guardado: Página " + self.currentPage + " para " + self.itemId);
        })
        .catch(function(err) {
            console.error("Error al guardar progreso de kiosko:", err);
        });
    },

    // Precarga inteligente en segundo plano de las páginas adyacentes
    preloadNeighborPages: function() {
        var pagesToPreload = [];
        var self = this;
        
        // Precargar la siguiente página (+1) si existe
        if (this.currentPage < this.totalPages) {
            pagesToPreload.push(this.currentPage + 1);
        }
        // Precargar la página subsiguiente (+2) si existe
        if (this.currentPage + 1 < this.totalPages) {
            pagesToPreload.push(this.currentPage + 2);
        }
        // Precargar la página anterior (-1) si existe
        if (this.currentPage > 1) {
            pagesToPreload.push(this.currentPage - 1);
        }
        
        for (var pi = 0; pi < pagesToPreload.length; pi++) {
            var page = pagesToPreload[pi];
            var cacheKey = self.itemId + "_" + page;
            if (!self.preloadedImages[cacheKey]) {
                var img = new Image();
                img.src = "/api/kiosko/page/" + self.itemId + "/" + page;
                self.preloadedImages[cacheKey] = img;
            }
        }
    }
};

// Exportar globalmente
window.Kiosko = Kiosko;
