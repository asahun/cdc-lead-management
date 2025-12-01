/**
 * Scheduled emails management functionality.
 */

(function() {
  'use strict';

  function loadScheduledEmails(leadId) {
    const container = document.getElementById('scheduled-emails-list');
    if (!container) return;

    fetch(`/leads/${leadId}/scheduled-emails`)
      .then(response => response.json())
      .then(emails => {
        if (emails.length === 0) {
          container.innerHTML = '<p class="text-muted">No scheduled or failed emails.</p>';
          return;
        }

        const PROFILE_LABELS = {
          fisseha: 'Fisseha',
          abby: 'Abby',
        };

        const html = emails.map(email => {
          const scheduledDate = new Date(email.scheduled_at);
          const formattedDate = scheduledDate.toLocaleString();
          const profileLabel = PROFILE_LABELS[email.profile] || (email.profile ? email.profile : 'Fisseha');
          
          let statusClass = 'status-pending';
          let statusText = email.status;
          if (email.status === 'sent') {
            statusClass = 'status-sent';
            statusText = 'Sent';
          } else if (email.status === 'failed') {
            statusClass = 'status-failed';
            statusText = 'Failed';
          } else if (email.status === 'missed') {
            statusClass = 'status-missed';
            statusText = 'Missed';
          } else if (email.status === 'cancelled') {
            statusClass = 'status-cancelled';
            statusText = 'Cancelled';
          }

          let actionsHtml = '';
          if (email.status === 'pending' || email.status === 'missed') {
            actionsHtml = `
              <button class="btn btn-sm btn-primary" onclick="editScheduledEmail(${leadId}, ${email.id})">Edit & Send</button>
              <button class="btn btn-sm btn-ghost" onclick="cancelScheduledEmail(${leadId}, ${email.id})">Cancel</button>
            `;
          } else if (email.status === 'failed') {
            actionsHtml = `
              <button class="btn btn-sm btn-primary" onclick="editScheduledEmail(${leadId}, ${email.id})">Edit & Reschedule</button>
            `;
          }

          const contactInfo = email.contact_name 
            ? `${email.contact_name}${email.contact_title ? ` (${email.contact_title})` : ''}`
            : email.to_email;

          return `
            <div class="scheduled-email-item">
              <div class="scheduled-email-header">
                <div>
                  <strong>${email.subject}</strong>
                  <span class="scheduled-email-status ${statusClass}">${statusText}</span>
                </div>
                <div class="scheduled-email-actions">
                  ${actionsHtml}
                </div>
              </div>
              <div class="scheduled-email-details">
                <div><strong>To:</strong> ${contactInfo} <span class="text-muted">(${email.to_email})</span></div>
                <div><strong>Scheduled for:</strong> ${formattedDate}</div>
                <div><strong>Profile:</strong> ${profileLabel}</div>
                ${email.sent_at ? `<div><strong>Sent at:</strong> ${new Date(email.sent_at).toLocaleString()}</div>` : ''}
                ${email.error_message ? `<div class="error-message"><strong>Error:</strong> ${email.error_message}</div>` : ''}
              </div>
            </div>
          `;
        }).join('');

        container.innerHTML = html;
      })
      .catch(error => {
        console.error('Error loading scheduled emails:', error);
        container.innerHTML = '<p class="text-error">Error loading scheduled emails.</p>';
      });
  }

  window.sendScheduledEmailNow = function(leadId, scheduledId) {
    if (!confirm('Send this email now?')) return;

    fetch(`/leads/${leadId}/scheduled-emails/${scheduledId}/send-now`, {
      method: 'POST',
    })
      .then(response => response.json())
      .then(data => {
        alert('Email sent successfully!');
        loadScheduledEmails(leadId);
        window.location.reload(); // Reload to show new attempt
      })
      .catch(error => {
        alert('Failed to send email: ' + error.message);
      });
  };

  window.cancelScheduledEmail = function(leadId, scheduledId) {
    if (!confirm('Cancel this scheduled email?')) return;

    fetch(`/leads/${leadId}/scheduled-emails/${scheduledId}`, {
      method: 'DELETE',
    })
      .then(response => response.json())
      .then(data => {
        alert('Email cancelled successfully!');
        loadScheduledEmails(leadId);
      })
      .catch(error => {
        alert('Failed to cancel email: ' + error.message);
      });
  };

  window.editScheduledEmail = function(leadId, scheduledId) {
    // Fetch scheduled email data
    fetch(`/leads/${leadId}/scheduled-emails/${scheduledId}`)
      .then(response => response.json())
      .then(email => {
        // Open the email modal with the scheduled email data
        const modal = document.getElementById('email-modal');
        const toInput = document.getElementById('email-to');
        const subjectInput = document.getElementById('email-subject');
        const bodyEditor = document.getElementById('email-body-editor');
        const bodyHidden = document.getElementById('email-body-hidden');
        const sendBtn = document.getElementById('email-send-btn');
        const scheduleBtn = document.getElementById('email-schedule-btn');
        const scheduleGroup = document.getElementById('schedule-group');
        const scheduledDateInput = document.getElementById('email-scheduled-date');
        const scheduledTimeInput = document.getElementById('email-scheduled-time');
        
        // Set contact info
        const contactName = email.contact_name || email.to_email;
        toInput.value = `${contactName} <${email.to_email}>`;
        
        // Set subject and body
        subjectInput.value = email.subject;
        bodyEditor.innerHTML = email.body;
        bodyHidden.value = email.body;
        
        // Pre-populate scheduled date/time if editing a scheduled email
        if (email.scheduled_at) {
          const scheduledDate = new Date(email.scheduled_at);
          const year = scheduledDate.getFullYear();
          const month = String(scheduledDate.getMonth() + 1).padStart(2, '0');
          const day = String(scheduledDate.getDate()).padStart(2, '0');
          const hours = String(scheduledDate.getHours()).padStart(2, '0');
          const minutes = String(scheduledDate.getMinutes()).padStart(2, '0');
          
          scheduledDateInput.value = `${year}-${month}-${day}`;
          scheduledTimeInput.value = `${hours}:${minutes}`;
        }
        
        // Hide schedule group initially (user can click Schedule to reschedule)
        scheduleGroup.style.display = 'none';
        scheduleBtn.textContent = 'Schedule';
        sendBtn.style.display = 'inline-flex';
        sendBtn.textContent = 'Send Now';
        
        // Store scheduled email ID for update
        window.currentScheduledEmailId = scheduledId;
        if (window.emailComposeModule && typeof window.emailComposeModule.setContext === 'function') {
          window.emailComposeModule.setContext({
            leadId,
            contactId: email.contact_id || null,
          });
        }
        
        // Open modal
        modal.style.display = 'flex';
      })
      .catch(error => {
        console.error('Error loading scheduled email:', error);
        alert('Failed to load scheduled email: ' + error.message);
      });
  };

  window.rescheduleFailedEmail = function(leadId, scheduledId) {
    // Same as edit for failed emails
    window.editScheduledEmail(leadId, scheduledId);
  };

  // Load scheduled emails when page loads
  document.addEventListener('DOMContentLoaded', () => {
    const leadIdMatch = window.location.pathname.match(/\/leads\/(\d+)\//);
    if (leadIdMatch) {
      const leadId = parseInt(leadIdMatch[1], 10);
      loadScheduledEmails(leadId);
    }
  });
})();

