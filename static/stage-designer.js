// Global state
let currentTool = 'select';
let selectedElements = [];
let objects = [];
let lines = [];
let labels = [];
let drawings = []; // For freehand drawings
let currentPath = null; // Current path being drawn
let currentDesignId = null;
let objectLibrary = [];
let templates = [];
let isDrawingLine = false;
let lineStart = null;
let isDragging = false;
let isResizing = false;
let isSelecting = false;
let isDrawing = false; // For pen/brush tool
let resizeHandle = null;
let dragOffset = { x: 0, y: 0 };
let objectIdCounter = 1;
let selectionStart = null;
let history = [];
let historyIndex = -1;
let maxHistory = 50;
let brushSize = 3; // Brush size
let brushColor = '#1f2937'; // Brush color

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    console.log('Stage Designer initializing...');
    loadObjectLibrary();
    loadTemplates();
    setupCanvasEvents();
    
    // Load design if editing
    const urlParams = new URLSearchParams(window.location.search);
    const designId = urlParams.get('design_id');
    if (designId) {
        console.log('Loading design:', designId);
        loadDesignData(parseInt(designId));
    }
    
    // Keyboard shortcuts
    document.addEventListener('keydown', handleKeyDown);
    
    // Initialize history with empty state
    saveState();
    console.log('Stage Designer initialized');
});

function handleKeyDown(e) {
    // Prevent default for shortcuts we handle
    if ((e.ctrlKey || e.metaKey) && ['s', 'd', 'z', 'y', 'a'].includes(e.key.toLowerCase())) {
        e.preventDefault();
    }
    
    // Delete
    if (e.key === 'Delete' && selectedElements.length > 0) {
        deleteSelected();
    }
    // Escape - deselect
    if (e.key === 'Escape') {
        deselectAll();
    }
    // Ctrl+S - Save
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        showSaveModal();
    }
    // Ctrl+D - Duplicate
    if ((e.ctrlKey || e.metaKey) && e.key === 'd' && selectedElements.length > 0) {
        duplicateSelected();
    }
    // Ctrl+Z - Undo
    if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        undo();
    }
    // Ctrl+Y - Redo
    if ((e.ctrlKey || e.metaKey) && e.key === 'y') {
        redo();
    }
    // Tool shortcuts
    if (e.key === 'v' || e.key === 'V') {
        setTool('select');
    }
    if (e.key === 'l' || e.key === 'L') {
        setTool('line');
    }
    if (e.key === 't' || e.key === 'T') {
        setTool('label');
    }
    if (e.key === 'p' || e.key === 'P') {
        setTool('pen');
    }
    if (e.key === 'b' || e.key === 'B') {
        setTool('brush');
    }
    // Ctrl+A - Select all
    if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
        selectAll();
    }
}

// Tool selection
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

// History management
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

// Load object library
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
            
            // Check if user is admin
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

// NEW: Delete library object (admin only)
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

// Load templates
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

// Tab switching
function showTab(tab) {
    document.getElementById('objectsTab').style.display = tab === 'objects' ? 'block' : 'none';
    document.getElementById('templatesTab').style.display = tab === 'templates' ? 'block' : 'none';
}

// Canvas setup
function setupCanvasEvents() {
    const canvas = document.getElementById('stageCanvas');
    
    // Drop objects
    canvas.addEventListener('dragover', e => e.preventDefault());
    canvas.addEventListener('drop', function(e) {
        e.preventDefault();
        const objectId = parseInt(e.dataTransfer.getData('objectId'));
        const obj = objectLibrary.find(o => o.id === objectId);
        
        if (obj) {
            const rect = canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            
            addObject(obj, x, y);
        }
    });
    
    // Mouse events
    canvas.addEventListener('mousedown', handleCanvasMouseDown);
    canvas.addEventListener('mousemove', handleCanvasMouseMove);
    canvas.addEventListener('mouseup', handleCanvasMouseUp);
    canvas.addEventListener('click', handleCanvasClick);
}

// NEW: Drawing tool handlers
function handleCanvasMouseDown(e) {
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    // Only start selection if clicking directly on the SVG canvas (not on objects)
    const target = e.target;
    const isCanvas = target.id === 'stageCanvas' || target.id === 'linesLayer';
    
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
        // Only start selection box if clicking on canvas, not on objects
        isSelecting = true;
        selectionStart = { x, y };
        
        // Clear selection if not holding Ctrl/Shift
        if (!e.ctrlKey && !e.shiftKey) {
            deselectAll();
        }
    }
}

function handleCanvasMouseMove(e) {
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    // Drawing with pen/brush
    if (isDrawing && currentPath) {
        currentPath.points.push({x, y});
        renderDrawingPreview(currentPath);
        return; // Don't do selection while drawing
    }
    
    // Selection box
    if (isSelecting && selectionStart) {
        const box = document.getElementById('selectionBox');
        box.style.display = 'block';
        
        const left = Math.min(selectionStart.x, x);
        const top = Math.min(selectionStart.y, y);
        const width = Math.abs(x - selectionStart.x);
        const height = Math.abs(y - selectionStart.y);
        
        box.style.left = left + 'px';
        box.style.top = top + 'px';
        box.style.width = width + 'px';
        box.style.height = height + 'px';
    }
}

function handleCanvasMouseUp(e) {
    // Finish drawing
    if (isDrawing && currentPath && currentPath.points.length > 1) {
        drawings.push(currentPath);
        renderDrawing(currentPath);
        saveState();
        currentPath = null;
        isDrawing = false;
        
        // Clear preview
        const preview = document.getElementById('drawingPreview');
        if (preview) preview.remove();
    }
    
    // Finish selection
    if (isSelecting) {
        isSelecting = false;
        const box = document.getElementById('selectionBox');
        
        if (box.style.display === 'block') {
            const rect = {
                left: parseInt(box.style.left),
                top: parseInt(box.style.top),
                right: parseInt(box.style.left) + parseInt(box.style.width),
                bottom: parseInt(box.style.top) + parseInt(box.style.height)
            };
            
            // Only select if the box is big enough (more than 5px in either direction)
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


// NEW: Render drawing preview while drawing
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

// NEW: Render finished drawing
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

function selectElementsInBox(rect) {
    // Don't clear selection - we handle that in mousedown
    let foundElements = [];
    
    // Check objects
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
    
    // Check labels
    labels.forEach(label => {
        const labelEl = document.getElementById(label.id);
        if (labelEl) {
            const labelRect = labelEl.getBoundingClientRect();
            const canvasRect = document.getElementById('stageCanvas').getBoundingClientRect();
            const objRect = {
                left: labelRect.left - canvasRect.left,
                top: labelRect.top - canvasRect.top,
                right: labelRect.right - canvasRect.left,
                bottom: labelRect.bottom - canvasRect.top
            };
            
            if (rectIntersect(rect, objRect)) {
                if (!isElementSelected(label)) {
                    foundElements.push({ element: label, type: 'label' });
                }
            }
        }
    });
    
    // Check lines
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
    
    // Check drawings
    drawings.forEach(drawing => {
        // Calculate bounding box of drawing
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
    
    // Add found elements to selection
    foundElements.forEach(item => {
        addToSelection(item.element, item.type);
    });
    
    updatePropertiesPanel();
    
    if (foundElements.length > 0) {
        showAlert(`Selected ${foundElements.length} element(s)`);
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

// Add object to canvas
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
    
    dragOffset.x = e.clientX - rect.left;
    dragOffset.y = e.clientY - rect.top;
    
    function onMouseMove(e) {
        if (!isDragging) return;
        
        const canvasRect = document.getElementById('stageCanvas').getBoundingClientRect();
        let newX = e.clientX - canvasRect.left - dragOffset.x;
        let newY = e.clientY - canvasRect.top - dragOffset.y;
        
        if (document.getElementById('snapToggle') && document.getElementById('snapToggle').checked) {
            newX = Math.round(newX / 20) * 20;
            newY = Math.round(newY / 20) * 20;
        }
        
        const dx = newX - obj.x;
        const dy = newY - obj.y;
        
        obj.x = Math.max(0, Math.min(newX, canvasRect.width - obj.width));
        obj.y = Math.max(0, Math.min(newY, canvasRect.height - obj.height));
        
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
        
        const dx = e.clientX - startX;
        const dy = e.clientY - startY;
        
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

// Line drawing
function handleLineDrawing(e) {
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
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
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
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

// Label placement
function handleLabelPlacement(e) {
    const rect = document.getElementById('stageCanvas').getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
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
    
    dragOffset.x = e.clientX - rect.left;
    dragOffset.y = e.clientY - rect.top;
    
    function onMouseMove(e) {
        if (!isDragging) return;
        
        const canvasRect = document.getElementById('stageCanvas').getBoundingClientRect();
        let newX = e.clientX - canvasRect.left - dragOffset.x;
        let newY = e.clientY - canvasRect.top - dragOffset.y;
        
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
        
        const dy = e.clientY - startY;
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

// Selection management
function selectElement(element, type) {
    if (!isElementSelected(element)) {
        addToSelection(element, type);
    }
    updatePropertiesPanel();
}

function deselectAll() {
    selectedElements.forEach(sel => {
        const el = document.getElementById(sel.element.id);
        if (el) el.classList.remove('selected');
    });
    selectedElements = [];
    updatePropertiesPanel();
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

// Properties panel
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
        panel.innerHTML = `
            <div id="multiSelection">
                <div class="property-group">
                    <h4><i class="fas fa-layer-group"></i> Multiple Selection</h4>
                    <p id="selectedCount" style="margin-bottom: 1rem; color: #6b7280;">${selectedElements.length} elements selected</p>
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

// Load saved designs modal
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

// Save and load
function showSaveModal() {
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
    
    // Generate thumbnail
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
        thumbnail: thumbnail, // Now includes actual thumbnail
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

// Also update saveAsTemplate to include thumbnail
async function saveAsTemplate() {
    const name = document.getElementById('saveName').value.trim();
    
    if (!name) {
        showAlert('Please enter a template name', 'error');
        return;
    }
    
    console.log('Saving template:', name);
    
    // Generate thumbnail
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
    
    document.getElementById('objectsLayer').innerHTML = '';
    document.getElementById('linesLayer').innerHTML = '';
    
    saveState();
    updatePropertiesPanel();
    showAlert('Canvas cleared');
}

// Export to PNG
// Add this function to stage-designer.js (replace the existing exportToPNG function)

function exportToPNG() {
    // Deselect all elements first (hide selection borders)
    const previousSelection = [...selectedElements];
    deselectAll();
    
    // Get canvas dimensions
    const canvas = document.getElementById('stageCanvas');
    const rect = canvas.getBoundingClientRect();
    
    // Create a temporary canvas
    const tempCanvas = document.createElement('canvas');
    tempCanvas.width = rect.width;
    tempCanvas.height = rect.height;
    const ctx = tempCanvas.getContext('2d');
    
    // Fill white background
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);
    
    // Draw grid if enabled
    const gridToggle = document.getElementById('gridToggle');
    if (gridToggle && gridToggle.checked) {
        ctx.strokeStyle = '#f0f0f0';
        ctx.lineWidth = 1;
        
        // Vertical lines
        for (let x = 0; x < tempCanvas.width; x += 20) {
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, tempCanvas.height);
            ctx.stroke();
        }
        
        // Horizontal lines
        for (let y = 0; y < tempCanvas.height; y += 20) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(tempCanvas.width, y);
            ctx.stroke();
        }
    }
    
    // Function to draw everything
    const drawCanvas = () => {
        return new Promise((resolve) => {
            let loadedImages = 0;
            let totalImages = objects.length;
            
            // If no objects, just draw lines and labels
            if (totalImages === 0) {
                drawLinesAndLabels();
                resolve();
                return;
            }
            
            // Draw all objects
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
    
    // Function to draw lines, drawings, and labels
    const drawLinesAndLabels = () => {
        // Draw lines
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
        
        // Draw freehand drawings
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
        
        // Draw labels
        labels.forEach(label => {
            ctx.fillStyle = 'rgba(255, 255, 255, 0.95)';
            ctx.strokeStyle = '#e5e7eb';
            ctx.lineWidth = 1;
            
            // Measure text
            ctx.font = `${label.bold ? 'bold' : 'normal'} ${label.fontSize}px sans-serif`;
            const textWidth = ctx.measureText(label.text).width;
            const padding = 8;
            
            // Draw background
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
            
            // Draw text
            ctx.fillStyle = label.color;
            ctx.fillText(label.text, label.x, label.y);
        });
    };
    
    // Draw everything and export
    drawCanvas().then(() => {
        // Convert to blob and download
        tempCanvas.toBlob(function(blob) {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            
            // Generate filename
            const timestamp = new Date().toISOString().slice(0, 10);
            const designName = document.getElementById('saveName')?.value || 'stage_plan';
            const safeName = designName.replace(/[^a-z0-9]/gi, '_').toLowerCase();
            a.download = `${safeName}_${timestamp}.png`;
            
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
            
            showAlert('PNG exported successfully!');
            
            // Restore selection
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

// Helper function to generate thumbnail for saving
function generateThumbnail() {
    return new Promise((resolve) => {
        const canvas = document.getElementById('stageCanvas');
        const rect = canvas.getBoundingClientRect();
        
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = 400; // Thumbnail width
        tempCanvas.height = 300; // Thumbnail height
        const ctx = tempCanvas.getContext('2d');
        
        // Calculate scale to fit
        const scale = Math.min(
            tempCanvas.width / rect.width,
            tempCanvas.height / rect.height
        );
        
        // Center the scaled content
        const scaledWidth = rect.width * scale;
        const scaledHeight = rect.height * scale;
        const offsetX = (tempCanvas.width - scaledWidth) / 2;
        const offsetY = (tempCanvas.height - scaledHeight) / 2;
        
        // Fill background
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, tempCanvas.width, tempCanvas.height);
        
        ctx.save();
        ctx.translate(offsetX, offsetY);
        ctx.scale(scale, scale);
        
        let loadedImages = 0;
        const totalImages = objects.length;
        
        const finishThumbnail = () => {
            // Draw lines
            lines.forEach(line => {
                ctx.strokeStyle = line.color;
                ctx.lineWidth = line.width;
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(line.x1, line.y1);
                ctx.lineTo(line.x2, line.y2);
                ctx.stroke();
            });
            
            // Draw drawings
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
            
            // Draw labels
            labels.forEach(label => {
                ctx.font = `${label.bold ? 'bold' : 'normal'} ${label.fontSize}px sans-serif`;
                ctx.fillStyle = label.color;
                ctx.fillText(label.text, label.x, label.y);
            });
            
            ctx.restore();
            
            // Convert to data URL
            resolve(tempCanvas.toDataURL('image/png'));
        };
        
        if (totalImages === 0) {
            finishThumbnail();
            return;
        }
        
        // Draw objects
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

// Grid toggle
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

// Modal functions
function hideModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'none';
    }
}

// Upload object modal
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
                
                // Clear form
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

// Utility functions
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

// Close modals when clicking outside
window.onclick = function(event) {
    if (event.target.classList.contains('modal')) {
        event.target.style.display = 'none';
    }
}