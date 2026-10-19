/*
 * event-tasks.js - tick event tasks on and off (event page + Tasks page).
 *
 * Rows look like <li class="sw-task" data-task="ID"> with a <button data-task-toggle="ID">.
 * A task can appear more than once on a page, so every copy is kept in step, and the
 * counters around them ([data-task-count], [data-task-open], [data-task-bar]) are recounted.
 * Needs sw-ui.js (SW.api, SW.toast).
 */
(function () {
  function recount() {
    document.querySelectorAll('[data-task-group]').forEach((g) => {
      const rows = g.querySelectorAll('.sw-task');
      const done = g.querySelectorAll('.sw-task.done').length;
      const total = rows.length;
      g.querySelectorAll('[data-task-count]').forEach((n) => { n.textContent = `${done}/${total}`; });
      g.querySelectorAll('[data-task-open]').forEach((n) => { n.textContent = total - done; n.hidden = total - done === 0; });
      g.querySelectorAll('[data-task-bar]').forEach((n) => { n.style.width = total ? `${Math.round(done / total * 100)}%` : '0'; });
    });
    document.querySelectorAll('[data-shift-tasks]').forEach((chip) => {
      const rows = document.querySelectorAll(`.sw-task[data-shift="${chip.dataset.shiftTasks}"]`);
      if (!rows.length) return;
      chip.textContent = `${document.querySelectorAll(`.sw-task.done[data-shift="${chip.dataset.shiftTasks}"]`).length}/${rows.length} tasks`;
    });
  }

  function paint(id, done, by) {
    document.querySelectorAll(`.sw-task[data-task="${id}"]`).forEach((row) => {
      row.classList.toggle('done', done);
      const b = row.querySelector('[data-task-toggle]');
      if (b) b.setAttribute('aria-pressed', done ? 'true' : 'false');
      const who = row.querySelector('[data-task-by]');
      if (who) who.textContent = done && by ? `Done by ${by}` : '';
      const due = row.querySelector('[data-due]');
      if (due) {
        const late = !done && due.dataset.due < new Date().toISOString().slice(0, 10);
        due.classList.toggle('bad', late); due.classList.toggle('plain', !late);
      }
    });
    recount();
  }

  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-task-toggle]');
    if (!b) return;
    e.preventDefault();
    const id = b.dataset.taskToggle;
    const row = b.closest('.sw-task');
    const was = row.classList.contains('done');
    if (b.disabled) return;
    b.disabled = true;
    paint(id, !was, '');                                   // instant feedback
    try {
      const r = await SW.api('POST', `/event-tasks/${id}/toggle`, { completed: !was });
      paint(id, r.task.done, r.task.completed_by);
    } catch (err) {
      paint(id, was, '');
      SW.toast(err.message || 'Could not update the task', 'error');
    } finally { b.disabled = false; }
  });

  document.addEventListener('DOMContentLoaded', recount);
})();
