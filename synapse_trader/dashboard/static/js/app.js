// --- synapse_trader/dashboard/static/js/app.js ---

document.addEventListener("DOMContentLoaded", () => {

    const statusIndicator = document.getElementById("status-indicator");
    const statusText = document.getElementById("status-text");
    const positionsTableBody = document.getElementById("positions-tbody");
    const historyTableBody = document.getElementById("history-tbody");

    // Guarda o P/L atual por símbolo (para fácil atualização)
    const currentPnl = {};

    // --- ATUALIZAÇÃO: Função para atualizar PNL na Tabela ---
    function updatePositionPnl(symbol, pnl) {
        currentPnl[symbol] = pnl; // Guarda o último PNL
        const row = document.getElementById(`pos-${symbol}`); // Procura a linha pelo ID
        if (row) {
            const pnlCell = row.querySelector(".pnl-cell"); // Procura a célula pela classe
            if (pnlCell) {
                const pnlValue = parseFloat(pnl);
                pnlCell.textContent = `$${pnlValue.toFixed(2)}`;
                pnlCell.className = `pnl-cell ${pnlValue >= 0 ? 'profit' : 'loss'}`;
            }
        }
    }
    // --- FIM DA ATUALIZAÇÃO ---

    // --- 1. Conexão WebSocket (para P/L em tempo real) ---
    function connectWebSocket() {
        const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/dashboard`;
        
        console.log(`A conectar ao WebSocket: ${wsUrl}`);
        const socket = new WebSocket(wsUrl);

        socket.onopen = () => {
            console.log("WebSocket conectado.");
        };

        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                // --- ATUALIZAÇÃO: Chama a função de atualização ---
                if (data.symbol && data.pnl !== undefined) {
                    updatePositionPnl(data.symbol, data.pnl);
                }
                // --- FIM DA ATUALIZAÇÃO ---
            } catch (error) {
                console.error("Erro ao processar mensagem WS:", error, event.data);
            }
        };

        socket.onclose = () => {
            console.log("WebSocket desconectado. A tentar reconectar em 3s...");
            // Limpa PNLs antigos ao desconectar
            Object.keys(currentPnl).forEach(symbol => updatePositionPnl(symbol, '---'));
            setTimeout(connectWebSocket, 3000); 
        };

        socket.onerror = (error) => {
            console.error("Erro no WebSocket:", error);
            socket.close(); // Força o onclose a ser chamado
        };
    }
    
    // --- ATUALIZADO: Inicia a conexão ---
    connectWebSocket(); 
    // --- FIM DA ATUALIZAÇÃO ---

    // --- 2. Polling (Fetch) dos Endpoints REST ---
    
    async function fetchStatus() {
        // (Lógica idêntica à anterior)
        try {
            const response = await fetch("/api/v1/status");
            const data = await response.json();
            if (data.status === "online") statusIndicator.classList.add("online");
            else statusIndicator.classList.remove("online");
            statusText.textContent = `Trend: ${data.market_trend}`;
        } catch (error) {
            console.error("Erro ao buscar status:", error);
            statusIndicator.classList.remove("online");
            statusText.textContent = "Erro de conexão";
        }
    }

    async function fetchPositions() {
        try {
            const response = await fetch("/api/v1/positions");
            const data = await response.json();
            
            positionsTableBody.innerHTML = ""; // Limpa a tabela
            
            data.positions.forEach(pos => {
                const row = document.createElement("tr");
                // --- ATUALIZAÇÃO: Adiciona ID à linha e classe à célula PNL ---
                row.id = `pos-${pos.symbol}`; 
                const initialPnl = currentPnl[pos.symbol] !== undefined ? parseFloat(currentPnl[pos.symbol]).toFixed(2) : '---';
                const initialPnlClass = currentPnl[pos.symbol] !== undefined ? (currentPnl[pos.symbol] >= 0 ? 'profit' : 'loss') : '';

                row.innerHTML = `
                    <td>${pos.symbol}</td>
                    <td>${pos.side}</td>
                    <td>${pos.quantity}</td>
                    <td>$${parseFloat(pos.entry_price).toFixed(4)}</td>
                    <td>$${parseFloat(pos.sl_price).toFixed(4)}</td>
                    <td class="pnl-cell ${initialPnlClass}">$${initialPnl}</td> 
                `;
                // --- FIM DA ATUALIZAÇÃO ---
                positionsTableBody.appendChild(row);
            });

        } catch (error) {
            console.error("Erro ao buscar posições:", error);
        }
    }

    async function fetchHistory() {
        // (Lógica idêntica à anterior)
         try {
            const response = await fetch("/api/v1/trade_history");
            const data = await response.json();
            historyTableBody.innerHTML = ""; 
            data.history.forEach(trade => {
                const pnlClass = trade.pnl >= 0 ? "profit" : "loss";
                const pnl = parseFloat(trade.pnl).toFixed(2);
                const pnlPercent = parseFloat(trade.pnl_percent).toFixed(2);
                const row = document.createElement("tr");
                row.innerHTML = `
                    <td>${new Date(trade.timestamp_exit).toLocaleString()}</td>
                    <td>${trade.symbol}</td>
                    <td>${trade.side}</td>
                    <td class="${pnlClass}">$${pnl} (${pnlPercent}%)</td>
                `;
                historyTableBody.appendChild(row);
            });
        } catch (error) {
            console.error("Erro ao buscar histórico:", error);
        }
    }

    function runPolling() {
        fetchStatus();
        fetchPositions();
        fetchHistory();
    }
    
    runPolling(); 
    setInterval(runPolling, 5000); 

});