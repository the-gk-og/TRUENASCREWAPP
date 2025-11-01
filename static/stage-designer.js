// Global state
let currentTool = 'select';
let selectedElements = [];
let objects = [];
let lines = [];
let labels = [];
let drawings = [];
let currentPath = null;
let currentDesignId = null;
let currentDesignName = null; // NEW: Track design name
let objectLibrary = [];
let templates = [];
let isDrawingLine = false;
let lineStart = null;
let isDragging = false;
let isResizing = false;
let isSelecting = false;
let isDrawing = false;
let resizeHandle = null;
let dragOffset = { x: 0, y: 0 };
let objectIdCounter = 1;
let selectionStart = null;
let history = [];
let historyIndex = -1;
let maxHistory = 50;
let brushSize = 3;
let brushColor = '#1f2937';

// NEW: Zoom functionality
let zoomLevel = 1;
let isPanning = false;
let panStart = { x: 0, y: 0 };
let canvasOffset = { x: 0, y: 0 };

// NEW: Group manipulation
let groupDragStart = null;
let groupResizeStart = null;
let groupResizeStartBounds = null;
let isGroupDragging = false;
let isGroupResizing = false;

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    console.log('Stage Designer initializing...');
    loadObjectLibrary();
    loadTemplates();
    setupCanvasEvents();
    setupZoomControls(); // NEW
    
    const urlParams = new URLSearchParams(window.location.search);
    const designId = urlParams.get('design_id');
    if (designId) {
        console.log('Loading design:', designId);
        loadDesignData(parseInt(designId));
    }
    
    document.addEventListener('keydown', handleKeyDown);
    saveState();
    console.log('Stage Designer initialized');
});

// NEW: Setup zoom controls
function setupZoomControls() {
    const canvas = document.getElementById('stageCanvas');
    
    // Mouse wheel zoom
    canvas.addEventListener('wheel', function(e) {
        if (e.ctrlKey) {
            e.preventDefault();
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            const newZoom = Math.max(0.1, Math.min(3, zoomLevel * delta));
            setZoom(newZoom);
        }
    }, { passive: false });
    
    // Space + drag to pan
    document.addEventListener('keydown', function(e) {
        if (e.code === 'Space' && !isPanning && currentTool === 'select') {
            e.preventDefault();
            canvas.style.cursor = 'grab';
        }
    });
    
    document.addEventListener('keyup', function(e) {
        if (e.code === 'Space') {
            isPanning = false;
            canvas.style.cursor = currentTool === 'select' ? 'default' : 'crosshair';
        }
    });
}

// NEW: Set zoom level
function setZoom(level) {
    zoomLevel = level;
    const canvas = document.getElementById('stageCanvas');
    const objectsLayer = document.getElementById('objectsLayer');
    const linesLayer = document.getElementById('linesLayer');
    
    const transform = `scale(${zoomLevel}) translate(${canvasOffset.x}px, ${canvasOffset.y}px)`;
    objectsLayer.style.transform = transform;
    linesLayer.style.transform = transform;
    objectsLayer.style.transformOrigin = '0 0';
    linesLayer.style.transformOrigin = '0 0';
    
    // Update zoom display
    const zoomDisplay = document.getElementById('zoomLevel');
    if (zoomDisplay) {
        zoomDisplay.textContent = Math.round(zoomLevel * 100) + '%';
    }
}

// NEW: Zoom controls
function zoomIn() {
    setZoom(Math.min(3, zoomLevel * 1.2));
}

function zoomOut() {
    setZoom(Math.max(0.1, zoomLevel / 1.2));
}

function resetZoom() {
    zoomLevel = 1;
    canvasOffset = { x: 0, y: 0 };
    setZoom(1);
}

// NEW: Toggle panel visibility
function togglePanel(panelId) {
    const panel = document.getElementById(panelId);
    const icon = document.querySelector(`[onclick="togglePanel('${panelId}')"] i`);
    
    if (panel.style.display === 'none') {
        panel.style.display = 'flex';
        if (icon) icon.className = 'fas fa-chevron-left';
    } else {
        panel.style.display = 'none';
        if (icon) icon.className = 'fas fa-chevron-right';
    }
    
    // Adjust grid layout
    updateGridLayout();
}

// NEW: Update grid layout based on visible panels
function updateGridLayout() {
    const container = document.querySelector('.designer-container');
    const leftPanel = document.getElementById('leftPanel');
    const rightPanel = document.getElementById('rightPanel');
    
    const leftVisible = leftPanel.style.display !== 'none';
    const rightVisible = rightPanel.style.display !== 'none';
    
    if (leftVisible && rightVisible) {
        container.style.gridTemplateColumns = '280px 1fr 300px';
    } else if (leftVisible) {
        container.style.gridTemplateColumns = '280px 1fr';
    } else if (rightVisible) {
        container.style.gridTemplateColumns = '1fr 300px';
    } else {
        container.style.gridTemplateColumns = '1fr';
    }
}

function handleKeyDown(e) {
    if ((e.ctrlKey || e.metaKey) && ['s', 'd', 'z', 'y', 'a'].includes(e.key.toLowerCase())) {
        e.preventDefault();
    }
    
    if (e.key === 'Delete' && selectedElements.length > 0) {
        deleteSelected();
    }
    if (e.key === 'Escape') {
        deselectAll();
    }
    // NEW: Quick save with Ctrl+S
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        if (currentDesignId) {
            quickSave(); // Save current design
        } else {
            showSaveModal(); // Show modal for new design
        }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'd' && selectedElements.length > 0) {
        duplicateSelected();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        undo();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
        redo();
    }
    if (e.key === 'v' || e.key === 'V') setTool('select');
    if (e.key === 'l' || e.key === 'L') setTool('line');
    if (e.key === 't' || e.key === 'T') setTool('label');
    if (e.key === 'p' || e.key === 'P') setTool('pen');
    if (e.key === 'b' || e.key === 'B') setTool('brush');
    if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
        selectAll();
    }
    // NEW: Zoom shortcuts
    if ((e.ctrlKey || e.metaKey) && e.key === '=') {
        e.preventDefault();
        zoomIn();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === '-') {
        e.preventDefault();
        zoomOut();
    }
    if ((e.ctrlKey || e.metaKey) && e.key === '0') {
        e.preventDefault();
        resetZoom();
    }
}

// NEW: Quick save (save without showing modal)
async function quickSave() {
    if (!currentDesignId) {
        showSaveModal();
        return;
    }
    
    showAlert('Saving...', 'success');
    
    const thumbnail = await generateThumbnail();
    
    const designData = {
        objects: objects,
        lines: lines,
        labels: labels,
        drawings: drawings
    };
    
    const payload = {
        name: currentDesignName || 'Untitled Design',
        design_data: designData,
        thumbnail: thumbnail,
        event_id: null, // Keep existing event
        save_to_stageplans: true
    };
    
    fetch(`/stage-designer/design/${currentDesignId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(result => {
        if (result.success) {
            showAlert('Design saved successfully!');
        } else {
            showAlert('Error saving: ' + (result.error || 'Unknown error'), 'error');
        }
    })
    .catch(err => {
        console.error('Save error:', err);
        showAlert('Error saving: ' + err.message, 'error');
    });
}

function setTool(tool) {
    currentTool = tool;
    document.querySelectorAll('.tool-btn').forEach(btn => btn.classList.remove('active'));
    const toolBtn = document.getElementById(tool + 'Tool');
    if (toolBtn) toolBtn.classList.add('active');
    
    const canvas = document.getElementById('stageCanvas');
    if (tool === 'line') {
        canvas.style.cursor = 'crosshair';
    } else if (tool === 'label') {
        canvas.style.cursor = 'text';
    } else if (tool === 'pen' || tool === 'brush') {
        canvas.style.cursor = 'crosshair';
    } else {
        canvas.style.cursor = 'default';
    }
}

function saveState() {
    const state = {
        objects: JSON.parse(JSON.stringify(objects)),
        lines: JSON.parse(JSON.stringify(lines)),
        labels: JSON.parse(JSON.stringify(labels)),
        drawings: JSON.parse(JSON.stringify(drawings))
    };
    
    if (historyIndex < history.length - 1) {
        history = history.slice(0, historyIndex + 1);
    }
    
    history.push(state);
    
    if (history.length > maxHistory) {
        history.shift();
    } else {
        historyIndex++;
    }
}

function undo() {
    if (historyIndex > 0) {
        historyIndex--;
        restoreState(history[historyIndex]);
        showAlert('Undo');
    }
}

function redo() {
    if (historyIndex < history.length - 1) {
        historyIndex++;
        restoreState(history[historyIndex]);
        showAlert('Redo');
    }
}

function restoreState(state) {
    objects = JSON.parse(JSON.stringify(state.objects));
    lines = JSON.parse(JSON.stringify(state.lines));
    labels = JSON.parse(JSON.stringify(state.labels));
    drawings = JSON.parse(JSON.stringify(state.drawings || []));
    
    document.getElementById('objectsLayer').innerHTML = '';
    document.getElementById('linesLayer').innerHTML = '';
    
    objects.forEach(obj => renderObject(obj));
    lines.forEach(line => renderLine(line));
    labels.forEach(label => renderLabel(label));
    drawings.forEach(drawing => renderDrawing(drawing));
    
    deselectAll();
}

function loadObjectLibrary() {
    console.log('Loading object library...');
    fetch('/stage-designer/objects')
        .then(r => r.json())
        .then(data => {
            console.log('Objects loaded:', data.length);
            objectLibrary = data;
            renderObjectLibrary();
        })
        .catch(err => {
            console.error('Error loading objects:', err);
            showAlert('Error loading object library', 'error');
        });
}

function renderObjectLibrary() {
    const container = document.getElementById('objectLibrary');
    const categories = {};
    
    objectLibrary.forEach(obj => {
        if (!categories[obj.category]) {
            categories[obj.category] = [];
        }
        categories[obj.category].push(obj);
    });
    
    container.innerHTML = '';
    
    Object.keys(categories).sort().forEach(category => {
        const categoryDiv = document.createElement('div');
        categoryDiv.className = 'object-category';
        
        const title = document.createElement('div');
        title.className = 'category-title';
        title.innerHTML = `<span>${category}</span><span>${categories[category].length}</span>`;
        categoryDiv.appendChild(title);
        
        const grid = document.createElement('div');
        grid.className = 'object-grid';
        
        categories[category].forEach(obj => {
            const item = document.createElement('div');
            item.className = 'object-item';
            item.draggable = true;
            
            const isAdmin = document.body.dataset.userIsAdmin === 'true';
            const deleteBtn = isAdmin ? `<button class="object-delete-btn" onclick="deleteLibraryObject(${obj.id}, event)" title="Delete object">×</button>` : '';
            
            item.innerHTML = `
                ${deleteBtn}
                <img src="${obj.image_data}" alt="${obj.name}">
                <span>${obj.name}</span>
            `;
            
            item.addEventListener('dragstart', function(e) {
                e.dataTransfer.setData('objectId', obj.id);
            });
            
            grid.appendChild(item);
        });
        
        categoryDiv.appendChild(grid);
        container.appendChild(categoryDiv);
    });
}

function deleteLibraryObject(id, event) {
    event.stopPropagation();
    
    if (!confirm('Delete this object from the library? This cannot be undone.')) return;
    
    fetch(`/stage-designer/objects/${id}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(result => {
            if (result.success) {
                showAlert('Object deleted from library');
                loadObjectLibrary();
            } else {
                showAlert('Error deleting object: ' + (result.error || 'Unknown error'), 'error');
            }
        })
        .catch(err => {
            console.error('Error deleting object:', err);
            showAlert('Error deleting object', 'error');
        });
}

function loadTemplates() {
    console.log('Loading templates...');
    fetch('/stage-designer/templates')
        .then(r => r.json())
        .then(data => {
            console.log('Templates loaded:', data.length);
            templates = data;
            renderTemplates();
        })
        .catch(err => console.error('Error loading templates:', err));
}

function renderTemplates() {
    const container = document.getElementById('templateLibrary');
    
    if (templates.length === 0) {
        container.innerHTML = '<p style="text-align: center; color: #9ca3af; padding: 2rem;">No templates saved yet</p>';
        return;
    }
    
    container.innerHTML = '';
    
    templates.forEach(template => {
        const card = document.createElement('div');
        card.className = 'template-card';
        card.innerHTML = `
            <div class="template-thumbnail">
                ${template.thumbnail ? `<img src="${template.thumbnail}" alt="${template.name}">` : '<div style="padding: 2rem; text-align: center; color: #9ca3af;">No Preview</div>'}
            </div>
            <div class="template-name">${template.name}</div>
            <div class="template-meta">Created ${new Date(template.created_at).toLocaleDateString()}</div>
            <button class="template-delete" onclick="deleteTemplate(${template.id}, event)" title="Delete template">×</button>
        `;
        
        card.addEventListener('click', function(e) {
            if (!e.target.classList.contains('template-delete')) {
                loadTemplate(template.id);
            }
        });
        
        container.appendChild(card);
    });
}

function loadTemplate(id) {
    if (!confirm('Load this template? Current work will be replaced.')) return;
    
    fetch(`/stage-designer/template/${id}/data`)
        .then(r => r.json())
        .then(data => {
            objects = data.design_data.objects || [];
            lines = data.design_data.lines || [];
            labels = data.design_data.labels || [];
            drawings = data.design_data.drawings || [];
            
            document.getElementById('objectsLayer').innerHTML = '';
            document.getElementById('linesLayer').innerHTML = '';
            
            objects.forEach(obj => renderObject(obj));
            lines.forEach(line => renderLine(line));
            labels.forEach(label => renderLabel(label));
            drawings.forEach(drawing => renderDrawing(drawing));
            
            saveState();
            showAlert('Template loaded successfully!');
        })
        .catch(err => {
            console.error('Error loading template:', err);
            showAlert('Error loading template', 'error');
        });
}

function deleteTemplate(id, event) {
    event.stopPropagation();
    if (!confirm('Delete this template?')) return;
    
    fetch(`/stage-designer/template/${id}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(result => {
            if (result.success) {
                showAlert('Template deleted');
                loadTemplates();
            }
        })
        .catch(err => {
            console.error('Error deleting template:', err);
            showAlert('Error deleting template', 'error');
        });
}

function showTab(tab) {
    document.getElementById('objectsTab').style.display = tab === 'objects' ? 'block' : 'none';
    document.getElementById('templatesTab').style.display = tab === 'templates' ? 'block' : 'none';
}

function setupCanvasEvents() {
    const canvas = document.getElementById('stageCanvas');
    
    canvas.addEventListener('dragover', e => e.preventDefault());
    canvas.addEventListener('drop', function(e) {
        e.preventDefault();
        const objectId = parseInt(e.dataTransfer.getData('objectId'));
        const obj = objectLibrary.find(o => o.id === objectId);
        
        if (obj) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) / zoomLevel - canvasOffset.x;
            const y = (e.clientY - rect.top) / zoomLevel - canvasOffset.y;
            
            addObject(obj, x, y);
        }
    });
    
    canvas.addEventListener('mousedown', handleCanvasMouseDown);
    canvas.addEventListener('mousemove', handleCanvasMouseMove);
    canvas.addEventListener('mouseup', handleCanvasMouseUp);
    canvas.addEventListener('click', handleCanvasClick);
}

function handleCanvasMouseDown(e) {
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = (e.clientX - rect.left) / zoomLevel - canvasOffset.x;
    const y = (e.clientY - rect.top) / zoomLevel - canvasOffset.y;
    
    // Space + drag for panning
    if (e.code === 'Space' || (currentTool === 'select' && e.button === 1)) {
        isPanning = true;
        panStart = { x: e.clientX, y: e.clientY };
        document.getElementById('stageCanvas').style.cursor = 'grabbing';
        e.preventDefault();
        return;
    }
    
    const target = e.target;
    const isCanvas = target.id === 'stageCanvas' || target.id === 'linesLayer' || target.classList.contains('selection-box');
    
    if (currentTool === 'pen' || currentTool === 'brush') {
        isDrawing = true;
        const strokeWidth = currentTool === 'brush' ? brushSize * 2 : brushSize;
        
        currentPath = {
            id: 'drawing_' + Date.now(),
            points: [{x, y}],
            color: brushColor,
            width: strokeWidth,
            tool: currentTool
        };
    } else if (currentTool === 'select' && isCanvas) {
        // Check if clicking on the group bounding box handles
        if (selectedElements.length > 1) {
            const handle = checkGroupHandleClick(e);
            if (handle === 'move') {
                isGroupDragging = true;
                groupDragStart = { x, y };
                return;
            } else if (handle) {
                isGroupResizing = true;
                groupResizeStart = { x, y, handle };
                groupResizeStartBounds = getSelectionBounds();
                return;
            }
        }
        
        // Start selection box
        isSelecting = true;
        selectionStart = { x, y };
        
        if (!e.ctrlKey && !e.shiftKey) {
            deselectAll();
        }
    }
}

// NEW: Check if clicking on group bounding box handles
function checkGroupHandleClick(e) {
    const bounds = getSelectionBounds();
    if (!bounds) return null;
    
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const clickX = (e.clientX - rect.left) / zoomLevel - canvasOffset.x;
    const clickY = (e.clientY - rect.top) / zoomLevel - canvasOffset.y;
    
    const handleSize = 15 / zoomLevel;
    
    // Check corners for resize
    const corners = [
        { x: bounds.left, y: bounds.top, type: 'nw' },
        { x: bounds.right, y: bounds.top, type: 'ne' },
        { x: bounds.left, y: bounds.bottom, type: 'sw' },
        { x: bounds.right, y: bounds.bottom, type: 'se' }
    ];
    
    for (let corner of corners) {
        if (Math.abs(clickX - corner.x) < handleSize && Math.abs(clickY - corner.y) < handleSize) {
            return corner.type;
        }
    }
    
    // Check if inside bounding box for move
    if (clickX >= bounds.left && clickX <= bounds.right && 
        clickY >= bounds.top && clickY <= bounds.bottom) {
        return 'move';
    }
    
    return null;
}

function handleCanvasMouseMove(e) {
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = (e.clientX - rect.left) / zoomLevel - canvasOffset.x;
    const y = (e.clientY - rect.top) / zoomLevel - canvasOffset.y;
    
    // Handle panning
    if (isPanning) {
        const dx = e.clientX - panStart.x;
        const dy = e.clientY - panStart.y;
        canvasOffset.x += dx / zoomLevel;
        canvasOffset.y += dy / zoomLevel;
        panStart = { x: e.clientX, y: e.clientY };
        setZoom(zoomLevel);
        return;
    }
    
    // NEW: Group dragging
    if (isGroupDragging && selectedElements.length > 1) {
        const dx = x - groupDragStart.x;
        const dy = y - groupDragStart.y;
        
        selectedElements.forEach(sel => {
            if (sel.type === 'object') {
                sel.element.x += dx;
                sel.element.y += dy;
                updateObjectPosition(sel.element);
            } else if (sel.type === 'label') {
                sel.element.x += dx;
                sel.element.y += dy;
                updateLabelPosition(sel.element);
            } else if (sel.type === 'line') {
                sel.element.x1 += dx;
                sel.element.y1 += dy;
                sel.element.x2 += dx;
                sel.element.y2 += dy;
                updateLinePosition(sel.element);
            } else if (sel.type === 'drawing') {
                sel.element.points.forEach(point => {
                    point.x += dx;
                    point.y += dy;
                });
                const el = document.getElementById(sel.element.id);
                if (el) {
                    const pathData = 'M ' + sel.element.points.map(p => `${p.x},${p.y}`).join(' L ');
                    el.setAttribute('d', pathData);
                }
            }
        });
        
        groupDragStart = { x, y };
        updatePropertiesPanel();
        renderGroupBoundingBox();
        return;
    }
    
    // NEW: Group resizing
    if (isGroupResizing && selectedElements.length > 1) {
        const bounds = groupResizeStartBounds;
        const centerX = bounds.left + bounds.width / 2;
        const centerY = bounds.top + bounds.height / 2;
        
        const handle = groupResizeStart.handle;
        let scaleX = 1, scaleY = 1;
        
        if (handle === 'se' || handle === 'ne' || handle === 'sw' || handle === 'nw') {
            const startDist = Math.sqrt(
                Math.pow(groupResizeStart.x - centerX, 2) + 
                Math.pow(groupResizeStart.y - centerY, 2)
            );
            const currentDist = Math.sqrt(
                Math.pow(x - centerX, 2) + 
                Math.pow(y - centerY, 2)
            );
            
            scaleX = scaleY = currentDist / startDist;
        }
        
        selectedElements.forEach(sel => {
            if (sel.type === 'object') {
                if (!sel.originalState) {
                    sel.originalState = {
                        x: sel.element.x,
                        y: sel.element.y,
                        width: sel.element.width,
                        height: sel.element.height
                    };
                }
                const relX = sel.originalState.x - centerX;
                const relY = sel.originalState.y - centerY;
                sel.element.x = centerX + relX * scaleX;
                sel.element.y = centerY + relY * scaleY;
                sel.element.width = sel.originalState.width * scaleX;
                sel.element.height = sel.originalState.height * scaleY;
                updateObjectPosition(sel.element);
            } else if (sel.type === 'label') {
                if (!sel.originalState) {
                    sel.originalState = {
                        x: sel.element.x,
                        y: sel.element.y,
                        fontSize: sel.element.fontSize
                    };
                }
                const relX = sel.originalState.x - centerX;
                const relY = sel.originalState.y - centerY;
                sel.element.x = centerX + relX * scaleX;
                sel.element.y = centerY + relY * scaleY;
                sel.element.fontSize = Math.max(8, sel.originalState.fontSize * scaleX);
                updateLabelPosition(sel.element);
            } else if (sel.type === 'line') {
                if (!sel.originalState) {
                    sel.originalState = {
                        x1: sel.element.x1,
                        y1: sel.element.y1,
                        x2: sel.element.x2,
                        y2: sel.element.y2
                    };
                }
                const relX1 = sel.originalState.x1 - centerX;
                const relY1 = sel.originalState.y1 - centerY;
                const relX2 = sel.originalState.x2 - centerX;
                const relY2 = sel.originalState.y2 - centerY;
                sel.element.x1 = centerX + relX1 * scaleX;
                sel.element.y1 = centerY + relY1 * scaleY;
                sel.element.x2 = centerX + relX2 * scaleX;
                sel.element.y2 = centerY + relY2 * scaleY;
                updateLinePosition(sel.element);
            }
        });
        
        updatePropertiesPanel();
        renderGroupBoundingBox();
        return;
    }
    
    if (isDrawing && currentPath) {
        currentPath.points.push({x, y});
        renderDrawingPreview(currentPath);
        return;
    }
    
    // NEW: Show line preview while drawing
    if (currentTool === 'line' && isDrawingLine && lineStart) {
        renderLinePreview(lineStart.x, lineStart.y, x, y);
        return;
    }
    
    if (isSelecting && selectionStart) {
        const box = document.getElementById('selectionBox');
        box.style.display = 'block';
        
        const left = Math.min(selectionStart.x, x) * zoomLevel + canvasOffset.x * zoomLevel;
        const top = Math.min(selectionStart.y, y) * zoomLevel + canvasOffset.y * zoomLevel;
        const width = Math.abs(x - selectionStart.x) * zoomLevel;
        const height = Math.abs(y - selectionStart.y) * zoomLevel;
        
        box.style.left = left + 'px';
        box.style.top = top + 'px';
        box.style.width = width + 'px';
        box.style.height = height + 'px';
    }
}

// NEW: Render line preview (dotted)
function renderLinePreview(x1, y1, x2, y2) {
    let preview = document.getElementById('linePreview');
    if (!preview) {
        preview = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        preview.id = 'linePreview';
        preview.style.stroke = '#1f2937';
        preview.style.strokeWidth = '2';
        preview.style.strokeDasharray = '5,5';
        preview.style.opacity = '0.6';
        document.getElementById('linesLayer').appendChild(preview);
    }
    
    preview.setAttribute('x1', x1);
    preview.setAttribute('y1', y1);
    preview.setAttribute('x2', x2);
    preview.setAttribute('y2', y2);
}

// NEW: Render group bounding box
function renderGroupBoundingBox() {
    if (selectedElements.length < 2) {
        const existingBox = document.getElementById('groupBoundingBox');
        if (existingBox) existingBox.remove();
        return;
    }
    
    const bounds = getSelectionBounds();
    if (!bounds) return;
    
    let bbox = document.getElementById('groupBoundingBox');
    if (!bbox) {
        bbox = document.createElementNS('http://www.w3.org/2000/svg', 'g');
        bbox.id = 'groupBoundingBox';
        document.getElementById('linesLayer').appendChild(bbox);
    }
    
    const padding = 5;
    
    bbox.innerHTML = `
        <rect x="${bounds.left - padding}" y="${bounds.top - padding}" 
              width="${bounds.width + padding * 2}" height="${bounds.height + padding * 2}"
              fill="none" stroke="#6366f1" stroke-width="2" stroke-dasharray="5,5" />
        
        <!-- Resize handles -->
        <circle cx="${bounds.left}" cy="${bounds.top}" r="8" fill="white" stroke="#6366f1" stroke-width="2" class="group-handle" data-handle="nw" />
        <circle cx="${bounds.right}" cy="${bounds.top}" r="8" fill="white" stroke="#6366f1" stroke-width="2" class="group-handle" data-handle="ne" />
        <circle cx="${bounds.left}" cy="${bounds.bottom}" r="8" fill="white" stroke="#6366f1" stroke-width="2" class="group-handle" data-handle="sw" />
        <circle cx="${bounds.right}" cy="${bounds.bottom}" r="8" fill="white" stroke="#6366f1" stroke-width="2" class="group-handle" data-handle="se" />
    `;
}

function handleCanvasMouseUp(e) {
    // Stop panning
    if (isPanning) {
        isPanning = false;
        document.getElementById('stageCanvas').style.cursor = currentTool === 'select' ? 'default' : 'crosshair';
        return;
    }
    
    // NEW: Stop group operations
    if (isGroupDragging) {
        isGroupDragging = false;
        saveState();
        return;
    }
    
    if (isGroupResizing) {
        isGroupResizing = false;
        // Clear original states
        selectedElements.forEach(sel => {
            delete sel.originalState;
        });
        groupResizeStartBounds = null;
        saveState();
        return;
    }
    
    if (isDrawing && currentPath && currentPath.points.length > 1) {
        drawings.push(currentPath);
        renderDrawing(currentPath);
        saveState();
        currentPath = null;
        isDrawing = false;
        
        const preview = document.getElementById('drawingPreview');
        if (preview) preview.remove();
    }
    
    if (isSelecting) {
        isSelecting = false;
        const box = document.getElementById('selectionBox');
        
        if (box.style.display === 'block') {
            const rect = {
                left: parseInt(box.style.left) / zoomLevel - canvasOffset.x,
                top: parseInt(box.style.top) / zoomLevel - canvasOffset.y,
                right: (parseInt(box.style.left) + parseInt(box.style.width)) / zoomLevel - canvasOffset.x,
                bottom: (parseInt(box.style.top) + parseInt(box.style.height)) / zoomLevel - canvasOffset.y
            };
            
            const boxWidth = parseInt(box.style.width);
            const boxHeight = parseInt(box.style.height);
            
            if (boxWidth > 5 || boxHeight > 5) {
                selectElementsInBox(rect);
            }
        }
        
        box.style.display = 'none';
        selectionStart = null;
    }
}

function renderDrawingPreview(path) {
    let preview = document.getElementById('drawingPreview');
    if (!preview) {
        preview = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        preview.id = 'drawingPreview';
        preview.style.fill = 'none';
        preview.style.stroke = path.color;
        preview.style.strokeWidth = path.width;
        preview.style.strokeLinecap = 'round';
        preview.style.strokeLinejoin = 'round';
        document.getElementById('linesLayer').appendChild(preview);
    }
    
    const pathData = 'M ' + path.points.map(p => `${p.x},${p.y}`).join(' L ');
    preview.setAttribute('d', pathData);
}

function renderDrawing(drawing) {
    const svg = document.getElementById('linesLayer');
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.id = drawing.id;
    path.classList.add('canvas-drawing');
    
    const pathData = 'M ' + drawing.points.map(p => `${p.x},${p.y}`).join(' L ');
    path.setAttribute('d', pathData);
    path.style.fill = 'none';
    path.style.stroke = drawing.color;
    path.style.strokeWidth = drawing.width;
    path.style.strokeLinecap = 'round';
    path.style.strokeLinejoin = 'round';
    
    path.addEventListener('click', function(e) {
        if (currentTool === 'select') {
            if (!e.ctrlKey && !e.shiftKey) {
                deselectAll();
            }
            selectElement(drawing, 'drawing');
            e.stopPropagation();
        }
    });
    
    svg.appendChild(path);
}

function handleCanvasClick(e) {
    if (currentTool === 'line') {
        handleLineDrawing(e);
    } else if (currentTool === 'label') {
        handleLabelPlacement(e);
    } else if (currentTool === 'select' && e.target === document.getElementById('stageCanvas')) {
        deselectAll();
    }
}

// NEW: Get bounding box of all selected elements
function getSelectionBounds() {
    if (selectedElements.length === 0) return null;
    
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    
    selectedElements.forEach(sel => {
        if (sel.type === 'object') {
            minX = Math.min(minX, sel.element.x);
            minY = Math.min(minY, sel.element.y);
            maxX = Math.max(maxX, sel.element.x + sel.element.width);
            maxY = Math.max(maxY, sel.element.y + sel.element.height);
        } else if (sel.type === 'label') {
            minX = Math.min(minX, sel.element.x);
            minY = Math.min(minY, sel.element.y);
            maxX = Math.max(maxX, sel.element.x + 100);
            maxY = Math.max(maxY, sel.element.y + sel.element.fontSize);
        } else if (sel.type === 'line') {
            minX = Math.min(minX, sel.element.x1, sel.element.x2);
            minY = Math.min(minY, sel.element.y1, sel.element.y2);
            maxX = Math.max(maxX, sel.element.x1, sel.element.x2);
            maxY = Math.max(maxY, sel.element.y1, sel.element.y2);
        }
    });
    
    return {
        left: minX,
        top: minY,
        right: maxX,
        bottom: maxY,
        width: maxX - minX,
        height: maxY - minY
    };
}

// NEW: Start group drag
function startGroupDrag() {
    if (selectedElements.length < 2) return;
    
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = (event.clientX - rect.left) / zoomLevel - canvasOffset.x;
    const y = (event.clientY - rect.top) / zoomLevel - canvasOffset.y;
    
    isGroupDragging = true;
    groupDragStart = { x, y };
    showAlert(`Moving ${selectedElements.length} elements`);
}

// NEW: Start group resize
function startGroupResize() {
    if (selectedElements.length < 2) return;
    
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = (event.clientX - rect.left) / zoomLevel - canvasOffset.x;
    const y = (event.clientY - rect.top) / zoomLevel - canvasOffset.y;
    
    isGroupResizing = true;
    groupResizeStart = { x, y };
    showAlert(`Resizing ${selectedElements.length} elements`);
}

function selectElementsInBox(rect) {
    let foundElements = [];
    
    objects.forEach(obj => {
        const objRect = {
            left: obj.x,
            top: obj.y,
            right: obj.x + obj.width,
            bottom: obj.y + obj.height
        };
        
        if (rectIntersect(rect, objRect)) {
            if (!isElementSelected(obj)) {
                foundElements.push({ element: obj, type: 'object' });
            }
        }
    });
    
    labels.forEach(label => {
        const objRect = {
            left: label.x,
            top: label.y - label.fontSize,
            right: label.x + 100,
            bottom: label.y
        };
        
        if (rectIntersect(rect, objRect)) {
            if (!isElementSelected(label)) {
                foundElements.push({ element: label, type: 'label' });
            }
        }
    });
    
    lines.forEach(line => {
        const lineRect = {
            left: Math.min(line.x1, line.x2) - 5,
            top: Math.min(line.y1, line.y2) - 5,
            right: Math.max(line.x1, line.x2) + 5,
            bottom: Math.max(line.y1, line.y2) + 5
        };
        
        if (rectIntersect(rect, lineRect)) {
            if (!isElementSelected(line)) {
                foundElements.push({ element: line, type: 'line' });
            }
        }
    });
    
    drawings.forEach(drawing => {
        if (drawing.points.length > 0) {
            let minX = drawing.points[0].x;
            let minY = drawing.points[0].y;
            let maxX = drawing.points[0].x;
            let maxY = drawing.points[0].y;
            
            drawing.points.forEach(point => {
                minX = Math.min(minX, point.x);
                minY = Math.min(minY, point.y);
                maxX = Math.max(maxX, point.x);
                maxY = Math.max(maxY, point.y);
            });
            
            const drawingRect = {
                left: minX - 5,
                top: minY - 5,
                right: maxX + 5,
                bottom: maxY + 5
            };
            
            if (rectIntersect(rect, drawingRect)) {
                if (!isElementSelected(drawing)) {
                    foundElements.push({ element: drawing, type: 'drawing' });
                }
            }
        }
    });
    
    foundElements.forEach(item => {
        addToSelection(item.element, item.type);
    });
    
    updatePropertiesPanel();
    renderGroupBoundingBox();
    
    if (foundElements.length > 0) {
        showAlert(`Selected ${selectedElements.length} element(s)`);
    }
}

function rectIntersect(rect1, rect2) {
    return !(rect2.left > rect1.right || 
             rect2.right < rect1.left || 
             rect2.top > rect1.bottom ||
             rect2.bottom < rect1.top);
}

function selectAll() {
    deselectAll();
    
    objects.forEach(obj => addToSelection(obj, 'object'));
    labels.forEach(label => addToSelection(label, 'label'));
    lines.forEach(line => addToSelection(line, 'line'));
    drawings.forEach(drawing => addToSelection(drawing, 'drawing'));
    
    updatePropertiesPanel();
    showAlert(`Selected ${selectedElements.length} elements`);
}

function addObject(libraryObj, x, y) {
    const obj = {
        id: 'obj_' + objectIdCounter++,
        libraryId: libraryObj.id,
        name: libraryObj.name,
        imageData: libraryObj.image_data,
        x: x - (libraryObj.default_width / 2),
        y: y - (libraryObj.default_height / 2),
        width: libraryObj.default_width,
        height: libraryObj.default_height,
        rotation: 0,
        label: libraryObj.name
    };
    
    objects.push(obj);
    renderObject(obj);
    saveState();
}

function renderObject(obj) {
    const objectsLayer = document.getElementById('objectsLayer');
    const div = document.createElement('div');
    div.id = obj.id;
    div.className = 'canvas-object';
    div.style.left = obj.x + 'px';
    div.style.top = obj.y + 'px';
    div.style.width = obj.width + 'px';
    div.style.height = obj.height + 'px';
    div.style.transform = `rotate(${obj.rotation}deg)`;
    div.style.pointerEvents = 'auto';
    
    div.innerHTML = `
        <img src="${obj.imageData}" alt="${obj.name}" draggable="false">
        <div class="resize-handle nw"></div>
        <div class="resize-handle ne"></div>
        <div class="resize-handle sw"></div>
        <div class="resize-handle se"></div>
    `;
    
    div.addEventListener('mousedown', function(e) {
        if (currentTool !== 'select') return;
        
        if (e.target.classList.contains('resize-handle')) {
            startResize(obj, e.target.classList[1], e);
        } else {
            if (!e.ctrlKey && !e.shiftKey) {
                if (!isElementSelected(obj)) {
                    deselectAll();
                }
            }
            selectElement(obj, 'object');
            startDrag(obj, e);
        }
        
        e.stopPropagation();
    });
    
    objectsLayer.appendChild(div);
}

function isElementSelected(element) {
    return selectedElements.some(sel => sel.element.id === element.id);
}

function addToSelection(element, type) {
    if (!isElementSelected(element)) {
        selectedElements.push({ element, type });
        const el = document.getElementById(element.id);
        if (el) el.classList.add('selected');
    }
}

function startDrag(obj, e) {
    isDragging = true;
    
    const rect = document.getElementById(obj.id).getBoundingClientRect();
    const canvasRect = document.getElementById('stageCanvas').getBoundingClientRect();
    
    dragOffset.x = (e.clientX - rect.left) / zoomLevel;
    dragOffset.y = (e.clientY - rect.top) / zoomLevel;
    
    function onMouseMove(e) {
        if (!isDragging) return;
        
        const canvasRect = document.getElementById('stageCanvas').getBoundingClientRect();
        let newX = (e.clientX - canvasRect.left) / zoomLevel - canvasOffset.x - dragOffset.x;
        let newY = (e.clientY - canvasRect.top) / zoomLevel - canvasOffset.y - dragOffset.y;
        
        if (document.getElementById('snapToggle') && document.getElementById('snapToggle').checked) {
            newX = Math.round(newX / 20) * 20;
            newY = Math.round(newY / 20) * 20;
        }
        
        const dx = newX - obj.x;
        const dy = newY - obj.y;
        
        obj.x = Math.max(0, newX);
        obj.y = Math.max(0, newY);
        
        selectedElements.forEach(sel => {
            if (sel.element.id !== obj.id) {
                if (sel.type === 'object') {
                    sel.element.x += dx;
                    sel.element.y += dy;
                    updateObjectPosition(sel.element);
                } else if (sel.type === 'label') {
                    sel.element.x += dx;
                    sel.element.y += dy;
                    updateLabelPosition(sel.element);
                } else if (sel.type === 'line') {
                    sel.element.x1 += dx;
                    sel.element.y1 += dy;
                    sel.element.x2 += dx;
                    sel.element.y2 += dy;
                    updateLinePosition(sel.element);
                }
            }
        });
        
        updateObjectPosition(obj);
        updatePropertiesPanel();
    }
    
    function onMouseUp() {
        if (isDragging) {
            saveState();
        }
        isDragging = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    }
    
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

function startResize(obj, handle, e) {
    isResizing = true;
    resizeHandle = handle;
    selectElement(obj, 'object');
    
    const startX = e.clientX;
    const startY = e.clientY;
    const startWidth = obj.width;
    const startHeight = obj.height;
    const startLeft = obj.x;
    const startTop = obj.y;
    
    function onMouseMove(e) {
        if (!isResizing) return;
        
        const dx = (e.clientX - startX) / zoomLevel;
        const dy = (e.clientY - startY) / zoomLevel;
        
        if (handle.includes('e')) {
            obj.width = Math.max(20, startWidth + dx);
        }
        if (handle.includes('w')) {
            const newWidth = Math.max(20, startWidth - dx);
            obj.x = startLeft + (startWidth - newWidth);
            obj.width = newWidth;
        }
        if (handle.includes('s')) {
            obj.height = Math.max(20, startHeight + dy);
        }
        if (handle.includes('n')) {
            const newHeight = Math.max(20, startHeight - dy);
            obj.y = startTop + (startHeight - newHeight);
            obj.height = newHeight;
        }
        
        updateObjectPosition(obj);
        updatePropertiesPanel();
    }
    
    function onMouseUp() {
        if (isResizing) {
            saveState();
        }
        isResizing = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    }
    
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    
    e.stopPropagation();
}

function updateObjectPosition(obj) {
    const div = document.getElementById(obj.id);
    if (div) {
        div.style.left = obj.x + 'px';
        div.style.top = obj.y + 'px';
        div.style.width = obj.width + 'px';
        div.style.height = obj.height + 'px';
        div.style.transform = `rotate(${obj.rotation}deg)`;
    }
}

function handleLineDrawing(e) {
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = (e.clientX - rect.left) / zoomLevel - canvasOffset.x;
    const y = (e.clientY - rect.top) / zoomLevel - canvasOffset.y;
    
    if (!isDrawingLine) {
        lineStart = { x, y };
        isDrawingLine = true;
        showAlert('Click to set end point');
    } else {
        const line = {
            id: 'line_' + Date.now(),
            x1: lineStart.x,
            y1: lineStart.y,
            x2: x,
            y2: y,
            color: '#1f2937',
            width: 2,
            style: 'solid'
        };
        
        lines.push(line);
        renderLine(line);
        saveState();
        
        isDrawingLine = false;
        lineStart = null;
        
        // Remove preview
        const preview = document.getElementById('linePreview');
        if (preview) preview.remove();
    }
}

function renderLine(line) {
    const svg = document.getElementById('linesLayer');
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.id = line.id;
    
    const lineEl = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    lineEl.classList.add('canvas-line');
    lineEl.setAttribute('x1', line.x1);
    lineEl.setAttribute('y1', line.y1);
    lineEl.setAttribute('x2', line.x2);
    lineEl.setAttribute('y2', line.y2);
    lineEl.style.stroke = line.color;
    lineEl.style.strokeWidth = line.width;
    
    if (line.style === 'dashed') {
        lineEl.style.strokeDasharray = '10,5';
    } else if (line.style === 'dotted') {
        lineEl.style.strokeDasharray = '2,5';
    }
    
    lineEl.addEventListener('click', function(e) {
        if (currentTool === 'select') {
            if (!e.ctrlKey && !e.shiftKey) {
                deselectAll();
            }
            selectElement(line, 'line');
            e.stopPropagation();
        }
    });
    
    const handle1 = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    handle1.classList.add('line-handle');
    handle1.setAttribute('cx', line.x1);
    handle1.setAttribute('cy', line.y1);
    handle1.setAttribute('r', 6);
    handle1.style.display = 'none';
    
    const handle2 = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    handle2.classList.add('line-handle');
    handle2.setAttribute('cx', line.x2);
    handle2.setAttribute('cy', line.y2);
    handle2.setAttribute('r', 6);
    handle2.style.display = 'none';
    
    handle1.addEventListener('mousedown', (e) => startLineHandleDrag(line, 'start', e));
    handle2.addEventListener('mousedown', (e) => startLineHandleDrag(line, 'end', e));
    
    g.appendChild(lineEl);
    g.appendChild(handle1);
    g.appendChild(handle2);
    svg.appendChild(g);
    
    const observer = new MutationObserver(() => {
        if (g.classList.contains('selected')) {
            handle1.style.display = 'block';
            handle2.style.display = 'block';
        } else {
            handle1.style.display = 'none';
            handle2.style.display = 'none';
        }
    });
    observer.observe(g, { attributes: true, attributeFilter: ['class'] });
}

function startLineHandleDrag(line, point, e) {
    e.stopPropagation();
    
    function onMouseMove(e) {
        const rect = document.getElementById('stageCanvas').getBoundingClientRect();
        const x = (e.clientX - rect.left) / zoomLevel - canvasOffset.x;
        const y = (e.clientY - rect.top) / zoomLevel - canvasOffset.y;
        
        if (point === 'start') {
            line.x1 = x;
            line.y1 = y;
        } else {
            line.x2 = x;
            line.y2 = y;
        }
        
        updateLinePosition(line);
    }
    
    function onMouseUp() {
        saveState();
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    }
    
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

function updateLinePosition(line) {
    const g = document.getElementById(line.id);
    if (g) {
        const lineEl = g.querySelector('.canvas-line');
        const handles = g.querySelectorAll('.line-handle');
        
        if (lineEl) {
            lineEl.setAttribute('x1', line.x1);
            lineEl.setAttribute('y1', line.y1);
            lineEl.setAttribute('x2', line.x2);
            lineEl.setAttribute('y2', line.y2);
        }
        
        if (handles.length === 2) {
            handles[0].setAttribute('cx', line.x1);
            handles[0].setAttribute('cy', line.y1);
            handles[1].setAttribute('cx', line.x2);
            handles[1].setAttribute('cy', line.y2);
        }
    }
}

function handleLabelPlacement(e) {
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = (e.clientX - rect.left) / zoomLevel - canvasOffset.x;
    const y = (e.clientY - rect.top) / zoomLevel - canvasOffset.y;
    
    const labelText = prompt('Enter label text:');
    if (!labelText) return;
    
    const label = {
        id: 'label_' + Date.now(),
        text: labelText,
        x: x,
        y: y,
        fontSize: 14,
        color: '#1f2937',
        bold: false
    };
    
    labels.push(label);
    renderLabel(label);
    saveState();
}

function renderLabel(label) {
    const objectsLayer = document.getElementById('objectsLayer');
    const div = document.createElement('div');
    div.id = label.id;
    div.className = 'canvas-label';
    div.style.left = label.x + 'px';
    div.style.top = label.y + 'px';
    div.style.fontSize = label.fontSize + 'px';
    div.style.color = label.color;
    div.style.fontWeight = label.bold ? 'bold' : 'normal';
    div.style.pointerEvents = 'auto';
    div.textContent = label.text;
    
    const handles = `
        <div class="resize-handle nw"></div>
        <div class="resize-handle ne"></div>
        <div class="resize-handle sw"></div>
        <div class="resize-handle se"></div>
    `;
    div.innerHTML = label.text + handles;
    
    div.addEventListener('mousedown', function(e) {
        if (currentTool === 'select') {
            if (e.target.classList.contains('resize-handle')) {
                startLabelResize(label, e.target.classList[1], e);
            } else {
                if (!e.ctrlKey && !e.shiftKey) {
                    if (!isElementSelected(label)) {
                        deselectAll();
                    }
                }
                selectElement(label, 'label');
                startLabelDrag(label, e);
            }
            e.stopPropagation();
        }
    });
    
    objectsLayer.appendChild(div);
}

function startLabelDrag(label, e) {
    isDragging = true;
    
    const rect = document.getElementById(label.id).getBoundingClientRect();
    const canvasRect = document.getElementById('stageCanvas').getBoundingClientRect();
    
    dragOffset.x = (e.clientX - rect.left) / zoomLevel;
    dragOffset.y = (e.clientY - rect.top) / zoomLevel;
    
    function onMouseMove(e) {
        if (!isDragging) return;
        
        const canvasRect = document.getElementById('stageCanvas').getBoundingClientRect();
        let newX = (e.clientX - canvasRect.left) / zoomLevel - canvasOffset.x - dragOffset.x;
        let newY = (e.clientY - canvasRect.top) / zoomLevel - canvasOffset.y - dragOffset.y;
        
        if (document.getElementById('snapToggle') && document.getElementById('snapToggle').checked) {
            newX = Math.round(newX / 20) * 20;
            newY = Math.round(newY / 20) * 20;
        }
        
        label.x = Math.max(0, newX);
        label.y = Math.max(0, newY);
        
        updateLabelPosition(label);
        updatePropertiesPanel();
    }
    
    function onMouseUp() {
        if (isDragging) {
            saveState();
        }
        isDragging = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    }
    
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
}

function startLabelResize(label, handle, e) {
    isResizing = true;
    selectElement(label, 'label');
    
    const startFontSize = label.fontSize;
    const startY = e.clientY;
    
    function onMouseMove(e) {
        if (!isResizing) return;
        
        const dy = (e.clientY - startY) / zoomLevel;
        label.fontSize = Math.max(8, Math.min(72, startFontSize + Math.round(dy / 5)));
        
        updateLabelPosition(label);
        updatePropertiesPanel();
    }
    
    function onMouseUp() {
        if (isResizing) {
            saveState();
        }
        isResizing = false;
        document.removeEventListener('mousemove', onMouseMove);
        document.removeEventListener('mouseup', onMouseUp);
    }
    
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
    
    e.stopPropagation();
}

function updateLabelPosition(label) {
    const div = document.getElementById(label.id);
    if (div) {
        div.style.left = label.x + 'px';
        div.style.top = label.y + 'px';
        div.style.fontSize = label.fontSize + 'px';
        div.style.color = label.color;
        div.style.fontWeight = label.bold ? 'bold' : 'normal';
        
        const textContent = label.text;
        div.childNodes[0].textContent = textContent;
    }
}

function selectElement(element, type) {
    if (!isElementSelected(element)) {
        addToSelection(element, type);
    }
    updatePropertiesPanel();
    renderGroupBoundingBox();
}

function deselectAll() {
    selectedElements.forEach(sel => {
        const el = document.getElementById(sel.element.id);
        if (el) el.classList.remove('selected');
    });
    selectedElements = [];
    updatePropertiesPanel();
    renderGroupBoundingBox();
}

function deleteSelected() {
    if (selectedElements.length === 0) return;
    
    const count = selectedElements.length;
    
    selectedElements.forEach(sel => {
        if (sel.type === 'object') {
            objects = objects.filter(o => o.id !== sel.element.id);
        } else if (sel.type === 'line') {
            lines = lines.filter(l => l.id !== sel.element.id);
        } else if (sel.type === 'label') {
            labels = labels.filter(l => l.id !== sel.element.id);
        } else if (sel.type === 'drawing') {
            drawings = drawings.filter(d => d.id !== sel.element.id);
        }
        
        const el = document.getElementById(sel.element.id);
        if (el) el.remove();
    });
    
    selectedElements = [];
    saveState();
    updatePropertiesPanel();
    showAlert(`Deleted ${count} element(s)`);
}

function duplicateSelected() {
    if (selectedElements.length === 0) return;
    
    const newSelections = [];
    
    selectedElements.forEach(sel => {
        if (sel.type === 'object') {
            const newObj = JSON.parse(JSON.stringify(sel.element));
            newObj.id = 'obj_' + objectIdCounter++;
            newObj.x += 20;
            newObj.y += 20;
            objects.push(newObj);
            renderObject(newObj);
            newSelections.push({ element: newObj, type: 'object' });
        } else if (sel.type === 'label') {
            const newLabel = JSON.parse(JSON.stringify(sel.element));
            newLabel.id = 'label_' + Date.now() + '_' + Math.random();
            newLabel.x += 20;
            newLabel.y += 20;
            labels.push(newLabel);
            renderLabel(newLabel);
            newSelections.push({ element: newLabel, type: 'label' });
        } else if (sel.type === 'line') {
            const newLine = JSON.parse(JSON.stringify(sel.element));
            newLine.id = 'line_' + Date.now() + '_' + Math.random();
            newLine.x1 += 20;
            newLine.y1 += 20;
            newLine.x2 += 20;
            newLine.y2 += 20;
            lines.push(newLine);
            renderLine(newLine);
            newSelections.push({ element: newLine, type: 'line' });
        }
    });
    
    deselectAll();
    selectedElements = newSelections;
    selectedElements.forEach(sel => {
        document.getElementById(sel.element.id).classList.add('selected');
    });
    
    saveState();
    updatePropertiesPanel();
    showAlert(`Duplicated ${selectedElements.length} element(s)`);
}

// NEW: Updated properties panel with group operations
function updatePropertiesPanel() {
    const panel = document.getElementById('propertiesPanel');
    
    if (selectedElements.length === 0) {
        panel.innerHTML = '<div id="noSelection" style="text-align: center; color: #9ca3af; padding: 2rem 0;"><i class="fas fa-hand-pointer" style="font-size: 3rem; margin-bottom: 1rem; opacity: 0.3;"></i><p>Select an object to edit its properties</p><p style="font-size: 0.85rem; margin-top: 1rem;"><strong>Tip:</strong> Drag to select multiple objects</p></div>';
        return;
    }
    
    if (selectedElements.length === 1) {
        const sel = selectedElements[0];
        
        if (sel.type === 'object') {
            panel.innerHTML = `
                <div class="property-group">
                    <h4><i class="fas fa-ruler-combined"></i> Position & Size</h4>
                    <div class="property-row">
                        <label>X:</label>
                        <input type="number" value="${Math.round(sel.element.x)}" onchange="updateObjectProperty('x', this.value)">
                    </div>
                    <div class="property-row">
                        <label>Y:</label>
                        <input type="number" value="${Math.round(sel.element.y)}" onchange="updateObjectProperty('y', this.value)">
                    </div>
                    <div class="property-row">
                        <label>Width:</label>
                        <input type="number" value="${Math.round(sel.element.width)}" onchange="updateObjectProperty('width', this.value)">
                    </div>
                    <div class="property-row">
                        <label>Height:</label>
                        <input type="number" value="${Math.round(sel.element.height)}" onchange="updateObjectProperty('height', this.value)">
                    </div>
                    <div class="property-row">
                        <label>Rotation:</label>
                        <input type="number" min="0" max="360" value="${sel.element.rotation}" onchange="updateObjectProperty('rotation', this.value)">
                    </div>
                </div>
                <div class="property-group">
                    <h4><i class="fas fa-tag"></i> Label</h4>
                    <div class="property-row">
                        <label>Text:</label>
                        <input type="text" value="${sel.element.label || ''}" onchange="updateObjectProperty('label', this.value)">
                    </div>
                </div>
                <div class="action-buttons">
                    <button class="action-btn action-btn-primary" onclick="duplicateSelected()">
                        <i class="fas fa-clone"></i> Duplicate
                    </button>
                    <button class="action-btn action-btn-danger" onclick="deleteSelected()">
                        <i class="fas fa-trash"></i> Delete
                    </button>
                </div>
            `;
        } else if (sel.type === 'line') {
            panel.innerHTML = `
                <div class="property-group">
                    <h4><i class="fas fa-grip-lines"></i> Line Properties</h4>
                    <div class="property-row">
                        <label>Color:</label>
                        <div class="color-picker-wrapper">
                            <input type="color" value="${sel.element.color}" onchange="updateLineProperty('color', this.value)">
                            <input type="text" value="${sel.element.color}" onchange="updateLineProperty('color', this.value)">
                        </div>
                    </div>
                    <div class="property-row">
                        <label>Width:</label>
                        <input type="number" min="1" max="20" value="${sel.element.width}" onchange="updateLineProperty('width', this.value)">
                    </div>
                    <div class="property-row">
                        <label>Style:</label>
                        <select onchange="updateLineProperty('style', this.value)">
                            <option value="solid" ${sel.element.style === 'solid' ? 'selected' : ''}>Solid</option>
                            <option value="dashed" ${sel.element.style === 'dashed' ? 'selected' : ''}>Dashed</option>
                            <option value="dotted" ${sel.element.style === 'dotted' ? 'selected' : ''}>Dotted</option>
                        </select>
                    </div>
                </div>
                <div class="action-buttons">
                    <button class="action-btn action-btn-danger" onclick="deleteSelected()" style="grid-column: 1 / -1;">
                        <i class="fas fa-trash"></i> Delete Line
                    </button>
                </div>
            `;
        } else if (sel.type === 'label') {
            panel.innerHTML = `
                <div class="property-group">
                    <h4><i class="fas fa-font"></i> Label Properties</h4>
                    <div class="property-row">
                        <label>Text:</label>
                        <input type="text" value="${sel.element.text}" onchange="updateLabelProperty('text', this.value)">
                    </div>
                    <div class="property-row">
                        <label>Size:</label>
                        <input type="number" min="8" max="72" value="${sel.element.fontSize}" onchange="updateLabelProperty('fontSize', this.value)">
                    </div>
                    <div class="property-row">
                        <label>Color:</label>
                        <div class="color-picker-wrapper">
                            <input type="color" value="${sel.element.color}" onchange="updateLabelProperty('color', this.value)">
                        </div>
                    </div>
                    <div class="property-row">
                        <label>Bold:</label>
                        <input type="checkbox" ${sel.element.bold ? 'checked' : ''} onchange="updateLabelProperty('bold', this.checked)">
                    </div>
                </div>
                <div class="action-buttons">
                    <button class="action-btn action-btn-danger" onclick="deleteSelected()" style="grid-column: 1 / -1;">
                        <i class="fas fa-trash"></i> Delete Label
                    </button>
                </div>
            `;
        } else if (sel.type === 'drawing') {
            panel.innerHTML = `
                <div class="property-group">
                    <h4><i class="fas fa-paint-brush"></i> Drawing Properties</h4>
                    <div class="property-row">
                        <label>Tool:</label>
                        <span>${sel.element.tool === 'pen' ? 'Pen' : 'Brush'}</span>
                    </div>
                    <div class="property-row">
                        <label>Points:</label>
                        <span>${sel.element.points.length}</span>
                    </div>
                </div>
                <div class="action-buttons">
                    <button class="action-btn action-btn-danger" onclick="deleteSelected()" style="grid-column: 1 / -1;">
                        <i class="fas fa-trash"></i> Delete Drawing
                    </button>
                </div>
            `;
        }
    } else {
        // NEW: Multiple selection - just show info, bounding box handles interaction
        const bounds = getSelectionBounds();
        panel.innerHTML = `
            <div id="multiSelection">
                <div class="property-group">
                    <h4><i class="fas fa-layer-group"></i> Multiple Selection</h4>
                    <p id="selectedCount" style="margin-bottom: 1rem; color: #6b7280;">${selectedElements.length} elements selected</p>
                    
                    <div class="property-row" style="margin-bottom: 1rem;">
                        <label style="flex: 1;">Group Bounds:</label>
                        <span style="font-size: 0.85rem; color: #6b7280;">${Math.round(bounds.width)} × ${Math.round(bounds.height)}px</span>
                    </div>
                    
                    <p style="font-size: 0.85rem; color: #6b7280; margin-bottom: 1rem; padding: 0.75rem; background: #ede9fe; border-radius: 6px;">
                        <i class="fas fa-info-circle"></i> Use the bounding box to move or resize all selected elements together
                    </p>
                    
                    <div class="action-buttons">
                        <button class="action-btn action-btn-primary" onclick="duplicateSelected()">
                            <i class="fas fa-clone"></i> Duplicate All
                        </button>
                        <button class="action-btn action-btn-danger" onclick="deleteSelected()">
                            <i class="fas fa-trash"></i> Delete All
                        </button>
                    </div>
                </div>
            </div>
        `;
    }
}

function updateObjectProperty(prop, value) {
    if (selectedElements.length !== 1 || selectedElements[0].type !== 'object') return;
    
    const obj = selectedElements[0].element;
    obj[prop] = parseFloat(value) || value;
    updateObjectPosition(obj);
    saveState();
}

function updateLineProperty(prop, value) {
    if (selectedElements.length !== 1 || selectedElements[0].type !== 'line') return;
    
    const line = selectedElements[0].element;
    line[prop] = prop === 'width' ? parseFloat(value) : value;
    
    const g = document.getElementById(line.id);
    if (g) {
        const lineEl = g.querySelector('.canvas-line');
        if (lineEl) {
            if (prop === 'color') {
                lineEl.style.stroke = value;
            } else if (prop === 'width') {
                lineEl.style.strokeWidth = value;
            } else if (prop === 'style') {
                if (value === 'dashed') {
                    lineEl.style.strokeDasharray = '10,5';
                } else if (value === 'dotted') {
                    lineEl.style.strokeDasharray = '2,5';
                } else {
                    lineEl.style.strokeDasharray = 'none';
                }
            }
        }
    }
    
    saveState();
}

function updateLabelProperty(prop, value) {
    if (selectedElements.length !== 1 || selectedElements[0].type !== 'label') return;
    
    const label = selectedElements[0].element;
    label[prop] = prop === 'fontSize' ? parseFloat(value) : value;
    updateLabelPosition(label);
    saveState();
}

function showLoadModal() {
    document.getElementById('loadModal').style.display = 'block';
    loadSavedDesigns();
}

function loadSavedDesigns() {
    const container = document.getElementById('designsList');
    container.innerHTML = '<p style="text-align: center; color: #9ca3af;">Loading...</p>';
    
    fetch('/stage-designer/designs')
        .then(r => r.json())
        .then(data => {
            if (data.length === 0) {
                container.innerHTML = '<p style="text-align: center; color: #9ca3af; padding: 2rem;">No saved designs yet</p>';
                return;
            }
            
            container.innerHTML = '';
            
            data.forEach(design => {
                const card = document.createElement('div');
                card.className = 'design-card';
                card.innerHTML = `
                    <div class="design-thumbnail">
                        ${design.thumbnail ? `<img src="${design.thumbnail}" alt="${design.name}">` : '<div style="padding: 2rem; text-align: center; color: #9ca3af;">No Preview</div>'}
                    </div>
                    <div style="font-weight: 600; margin-bottom: 0.25rem;">${design.name}</div>
                    <div style="font-size: 0.85rem; color: #6b7280; margin-bottom: 0.5rem;">
                        ${design.event_name ? `Event: ${design.event_name}` : 'No event linked'}
                    </div>
                    <div style="font-size: 0.75rem; color: #9ca3af;">
                        By ${design.created_by} • ${new Date(design.updated_at).toLocaleDateString()}
                    </div>
                    <div class="design-actions">
                        <button class="btn btn-primary" onclick="loadDesignData(${design.id}); hideModal('loadModal')" style="flex: 1; padding: 0.5rem;">
                            <i class="fas fa-folder-open"></i> Load
                        </button>
                        <button class="btn btn-danger" onclick="deleteDesign(${design.id})" style="padding: 0.5rem 1rem;">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                `;
                container.appendChild(card);
            });
        })
        .catch(err => {
            console.error('Error loading designs:', err);
            container.innerHTML = '<p style="text-align: center; color: var(--danger); padding: 2rem;">Error loading designs</p>';
        });
}

function deleteDesign(id) {
    if (!confirm('Delete this design?')) return;
    
    fetch(`/stage-designer/design/${id}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(result => {
            if (result.success) {
                showAlert('Design deleted');
                loadSavedDesigns();
            }
        })
        .catch(err => {
            console.error('Error deleting design:', err);
            showAlert('Error deleting design', 'error');
        });
}

function showSaveModal() {
    // Pre-fill with current design name if editing
    if (currentDesignId && currentDesignName) {
        document.getElementById('saveName').value = currentDesignName;
    }
    document.getElementById('saveModal').style.display = 'block';
}

async function saveDesign() {
    const name = document.getElementById('saveName').value.trim();
    const eventId = document.getElementById('saveEvent').value;
    const saveToStagePlans = document.getElementById('saveToStagePlans').checked;
    
    if (!name) {
        showAlert('Please enter a design name', 'error');
        return;
    }
    
    console.log('Saving design:', name);
    
    showAlert('Generating preview...', 'success');
    const thumbnail = await generateThumbnail();
    
    const designData = {
        objects: objects,
        lines: lines,
        labels: labels,
        drawings: drawings
    };
    
    const payload = {
        name: name,
        event_id: eventId || null,
        design_data: designData,
        thumbnail: thumbnail,
        save_to_stageplans: saveToStagePlans
    };
    
    const url = currentDesignId 
        ? `/stage-designer/design/${currentDesignId}` 
        : '/stage-designer/design';
    
    const method = currentDesignId ? 'PUT' : 'POST';
    
    console.log('Saving to:', url, 'Method:', method);
    
    fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(r => {
        console.log('Response status:', r.status);
        return r.json();
    })
    .then(result => {
        console.log('Save result:', result);
        if (result.success) {
            currentDesignId = result.design_id;
            currentDesignName = name; // Save name for quick save
            showAlert('Design saved successfully!');
            hideModal('saveModal');
        } else {
            showAlert('Error saving design: ' + (result.error || 'Unknown error'), 'error');
        }
    })
    .catch(err => {
        console.error('Save error:', err);
        showAlert('Error saving design: ' + err.message, 'error');
    });
}

async function saveAsTemplate() {
    const name = document.getElementById('saveName').value.trim();
    
    if (!name) {
        showAlert('Please enter a template name', 'error');
        return;
    }
    
    console.log('Saving template:', name);
    
    showAlert('Generating preview...', 'success');
    const thumbnail = await generateThumbnail();
    
    const designData = {
        objects: objects,
        lines: lines,
        labels: labels,
        drawings: drawings
    };
    
    const payload = {
        name: name,
        design_data: designData,
        thumbnail: thumbnail
    };
    
    console.log('Template payload:', payload);
    
    fetch('/stage-designer/template', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(r => {
        console.log('Template response status:', r.status);
        return r.json();
    })
    .then(result => {
        console.log('Template result:', result);
        if (result.success) {
            showAlert('Template saved successfully!');
            hideModal('saveModal');
            loadTemplates();
        } else {
            showAlert('Error saving template: ' + (result.error || 'Unknown error'), 'error');
        }
    })
    .catch(err => {
        console.error('Template save error:', err);
        showAlert('Error saving template: ' + err.message, 'error');
    });
}

function loadDesignData(designId) {
    console.log('Loading design:', designId);
    fetch(`/stage-designer/design/${designId}/data`)
        .then(r => r.json())
        .then(data => {
            console.log('Design data loaded:', data);
            currentDesignId = designId;
            currentDesignName = data.name; // Store name for quick save
            objects = data.design_data.objects || [];
            lines = data.design_data.lines || [];
            labels = data.design_data.labels || [];
            drawings = data.design_data.drawings || [];
            
            document.getElementById('objectsLayer').innerHTML = '';
            document.getElementById('linesLayer').innerHTML = '';
            
            objects.forEach(obj => renderObject(obj));
            lines.forEach(line => renderLine(line));
            labels.forEach(label => renderLabel(label));
            drawings.forEach(drawing => renderDrawing(drawing));
            
            if (objects.length > 0) {
                const maxId = Math.max(...objects.map(o => parseInt(o.id.replace('obj_', '')) || 0));
                objectIdCounter = maxId + 1;
            }
            
            saveState();
            showAlert('Design loaded successfully!');
        })
        .catch(err => {
            console.error('Load error:', err);
            showAlert('Error loading design: ' + err.message, 'error');
        });
}

function clearCanvas() {
    if (!confirm('Clear the entire canvas? This cannot be undone.')) return;
    
    objects = [];
    lines = [];
    labels = [];
    drawings = [];
    selectedElements = [];
    currentDesignId = null;
    currentDesignName = null;
    
    document.getElementById('objectsLayer').innerHTML = '';
    document.getElementById('linesLayer').innerHTML = '';
    
    saveState();
    updatePropertiesPanel();
    showAlert('Canvas cleared');
}

function exportToPNG() {
    const previousSelection = [...selectedElements];
    deselectAll();
    
    const canvas = document.getElementById('stageCanvas');
    const rect = canvas.getBoundingClientRect();
    
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = rect.width;
    tempCanvas.height = rect.height;
    const ctx = tempCanvas.getContext('2d');
    
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);
    
    const gridToggle = document.getElementById('gridToggle');
    if (gridToggle && gridToggle.checked) {
        ctx.strokeStyle = '#f0f0f0';
        ctx.lineWidth = 1;
        
        for (let x = 0; x < tempCanvas.width; x += 20) {
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, tempCanvas.height);
            ctx.stroke();
        }
        
        for (let y = 0; y < tempCanvas.height; y += 20) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(tempCanvas.width, y);
            ctx.stroke();
        }
    }
    
    const drawCanvas = () => {
        return new Promise((resolve) => {
            let loadedImages = 0;
            let totalImages = objects.length;
            
            if (totalImages === 0) {
                drawLinesAndLabels();
                resolve();
                return;
            }
            
            objects.forEach(obj => {
                const img = new Image();
                img.crossOrigin = 'anonymous';
                img.onload = function() {
                    ctx.save();
                    ctx.translate(obj.x + obj.width / 2, obj.y + obj.height / 2);
                    ctx.rotate((obj.rotation * Math.PI) / 180);
                    ctx.drawImage(img, -obj.width / 2, -obj.height / 2, obj.width, obj.height);
                    ctx.restore();
                    
                    loadedImages++;
                    if (loadedImages === totalImages) {
                        drawLinesAndLabels();
                        resolve();
                    }
                };
                img.onerror = function() {
                    console.error('Failed to load image:', obj.imageData);
                    loadedImages++;
                    if (loadedImages === totalImages) {
                        drawLinesAndLabels();
                        resolve();
                    }
                };
                img.src = obj.imageData;
            });
        });
    };
    
    const drawLinesAndLabels = () => {
        lines.forEach(line => {
            ctx.strokeStyle = line.color;
            ctx.lineWidth = line.width;
            ctx.lineCap = 'round';
            
            if (line.style === 'dashed') {
                ctx.setLineDash([10, 5]);
            } else if (line.style === 'dotted') {
                ctx.setLineDash([2, 5]);
            } else {
                ctx.setLineDash([]);
            }
            
            ctx.beginPath();
            ctx.moveTo(line.x1, line.y1);
            ctx.lineTo(line.x2, line.y2);
            ctx.stroke();
            ctx.setLineDash([]);
        });
        
        drawings.forEach(drawing => {
            ctx.strokeStyle = drawing.color;
            ctx.lineWidth = drawing.width;
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            
            if (drawing.points.length > 1) {
                ctx.beginPath();
                ctx.moveTo(drawing.points[0].x, drawing.points[0].y);
                for (let i = 1; i < drawing.points.length; i++) {
                    ctx.lineTo(drawing.points[i].x, drawing.points[i].y);
                }
                ctx.stroke();
            }
        });
        
        labels.forEach(label => {
            ctx.fillStyle = 'rgba(255, 255, 255, 0.95)';
            ctx.strokeStyle = '#e5e7eb';
            ctx.lineWidth = 1;
            
            ctx.font = `${label.bold ? 'bold' : 'normal'} ${label.fontSize}px sans-serif`;
            const textWidth = ctx.measureText(label.text).width;
            const padding = 8;
            
            ctx.fillRect(
                label.x - padding / 2,
                label.y - label.fontSize - padding / 2,
                textWidth + padding,
                label.fontSize + padding
            );
            ctx.strokeRect(
                label.x - padding / 2,
                label.y - label.fontSize - padding / 2,
                textWidth + padding,
                label.fontSize + padding
            );
            
            ctx.fillStyle = label.color;
            ctx.fillText(label.text, label.x, label.y);
        });
    };
    
    drawCanvas().then(() => {
        tempCanvas.toBlob(function(blob) {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            
            const timestamp = new Date().toISOString().slice(0, 10);
            const designName = currentDesignName || 'stage_plan';
            const safeName = designName.replace(/[^a-z0-9]/gi, '_').toLowerCase();
            a.download = `${safeName}_${timestamp}.png`;
            
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            
            showAlert('PNG exported successfully!');
            
            if (previousSelection.length > 0) {
                previousSelection.forEach(sel => {
                    selectedElements.push(sel);
                    const el = document.getElementById(sel.element.id);
                    if (el) el.classList.add('selected');
                });
                updatePropertiesPanel();
            }
        }, 'image/png');
    });
}

function generateThumbnail() {
    return new Promise((resolve) => {
        const canvas = document.getElementById('stageCanvas');
        const rect = canvas.getBoundingClientRect();
        
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = 400;
        tempCanvas.height = 300;
        const ctx = tempCanvas.getContext('2d');
        
        const scale = Math.min(
            tempCanvas.width / rect.width,
            tempCanvas.height / rect.height
        );
        
        const scaledWidth = rect.width * scale;
        const scaledHeight = rect.height * scale;
        const offsetX = (tempCanvas.width - scaledWidth) / 2;
        const offsetY = (tempCanvas.height - scaledHeight) / 2;
        
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);
        
        ctx.save();
        ctx.translate(offsetX, offsetY);
        ctx.scale(scale, scale);
        
        let loadedImages = 0;
        const totalImages = objects.length;
        
        const finishThumbnail = () => {
            lines.forEach(line => {
                ctx.strokeStyle = line.color;
                ctx.lineWidth = line.width;
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(line.x1, line.y1);
                ctx.lineTo(line.x2, line.y2);
                ctx.stroke();
            });
            
            drawings.forEach(drawing => {
                ctx.strokeStyle = drawing.color;
                ctx.lineWidth = drawing.width;
                ctx.lineCap = 'round';
                ctx.lineJoin = 'round';
                
                if (drawing.points.length > 1) {
                    ctx.beginPath();
                    ctx.moveTo(drawing.points[0].x, drawing.points[0].y);
                    for (let i = 1; i < drawing.points.length; i++) {
                        ctx.lineTo(drawing.points[i].x, drawing.points[i].y);
                    }
                    ctx.stroke();
                }
            });
            
            labels.forEach(label => {
                ctx.font = `${label.bold ? 'bold' : 'normal'} ${label.fontSize}px sans-serif`;
                ctx.fillStyle = label.color;
                ctx.fillText(label.text, label.x, label.y);
            });
            
            ctx.restore();
            
            resolve(tempCanvas.toDataURL('image/png'));
        };
        
        if (totalImages === 0) {
            finishThumbnail();
            return;
        }
        
        objects.forEach(obj => {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = function() {
                ctx.save();
                ctx.translate(obj.x + obj.width / 2, obj.y + obj.height / 2);
                ctx.rotate((obj.rotation * Math.PI) / 180);
                ctx.drawImage(img, -obj.width / 2, -obj.height / 2, obj.width, obj.height);
                ctx.restore();
                
                loadedImages++;
                if (loadedImages === totalImages) {
                    finishThumbnail();
                }
            };
            img.onerror = function() {
                loadedImages++;
                if (loadedImages === totalImages) {
                    finishThumbnail();
                }
            };
            img.src = obj.imageData;
        });
    });
}

function toggleGrid() {
    const canvas = document.getElementById('stageCanvas');
    const gridToggle = document.getElementById('gridToggle');
    
    if (gridToggle && gridToggle.checked) {
        canvas.style.backgroundImage = 'linear-gradient(to right, #f0f0f0 1px, transparent 1px), linear-gradient(to bottom, #f0f0f0 1px, transparent 1px)';
        canvas.style.backgroundSize = '20px 20px';
        canvas.style.backgroundPosition = '-1px -1px';
    } else {
        canvas.style.backgroundImage = 'none';
    }
}

function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'none';
    }
}

function showUploadObjectModal() {
    document.getElementById('uploadObjectModal').style.display = 'block';
}

function uploadObject() {
    const name = document.getElementById('objectName').value.trim();
    const category = document.getElementById('objectCategory').value;
    const fileInput = document.getElementById('objectImage');
    const width = parseInt(document.getElementById('objectDefaultWidth').value);
    const height = parseInt(document.getElementById('objectDefaultHeight').value);
    
    if (!name || !fileInput.files[0]) {
        showAlert('Please provide name and image', 'error');
        return;
    }
    
    const reader = new FileReader();
    reader.onload = function(e) {
        const payload = {
            name: name,
            category: category,
            image_data: e.target.result,
            default_width: width,
            default_height: height,
            is_public: true
        };
        
        console.log('Uploading object:', name);
        
        fetch('/stage-designer/object', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(r => r.json())
        .then(result => {
            if (result.success) {
                showAlert('Object uploaded successfully!');
                hideModal('uploadObjectModal');
                loadObjectLibrary();
                
                document.getElementById('objectName').value = '';
                document.getElementById('objectImage').value = '';
            } else {
                showAlert('Error uploading object: ' + (result.error || 'Unknown error'), 'error');
            }
        })
        .catch(err => {
            console.error('Upload error:', err);
            showAlert('Error uploading object: ' + err.message, 'error');
        });
    };
    
    reader.readAsDataURL(fileInput.files[0]);
}

function showAlert(message, type = 'success') {
    console.log('Alert:', message, type);
    
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.innerHTML = `<i class="fas fa-${type === 'success' ? 'check-circle' : 'exclamation-circle'}"></i> ${message}`;
    alert.style.cssText = `
        position: fixed;
        top: 80px;
        right: 20px;
        z-index: 10000;
        padding: 1rem 1.5rem;
        background: ${type === 'success' ? '#10b981' : '#ef4444'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        font-weight: 500;
        animation: slideIn 0.3s ease;
    `;
    
    document.body.appendChild(alert);
    
    setTimeout(() => {
        alert.style.opacity = '0';
        alert.style.transition = 'opacity 0.3s';
        setTimeout(() => alert.remove(), 300);
    }, 3000);
}

window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.style.display = 'none';
    }
}