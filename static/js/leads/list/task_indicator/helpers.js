(function () {
  'use strict';

  function formatDate(date) {
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  function convertJourneyToSummary(journeyData) {
    const now = new Date();
    const overdue = [];
    const dueSoon = [];
    const upcoming = [];

    const channelIcons = {
      email: '📧',
      linkedin: '💼',
      mail: '📮',
    };

    const allMilestones = [
      ...(journeyData.email || []),
      ...(journeyData.linkedin || []),
      ...(journeyData.mail || []),
    ];

    allMilestones.forEach((milestone) => {
      if (milestone.status === 'completed' || milestone.status === 'skipped') {
        return;
      }

      const expectedDate = new Date(milestone.expected_date);
      const daysUntil = Math.ceil((expectedDate - now) / (1000 * 60 * 60 * 24));

      const taskData = {
        label: milestone.label,
        channel: milestone.channel,
        channel_icon: channelIcons[milestone.channel] || '•',
        expected_date: milestone.expected_date,
        days_until: daysUntil,
      };

      if (milestone.status === 'overdue' || daysUntil < 0) {
        overdue.push(taskData);
      } else if (daysUntil <= 2) {
        dueSoon.push(taskData);
      } else if (daysUntil <= 7) {
        upcoming.push(taskData);
      }
    });

    const priority =
      overdue.length > 0 ? 'overdue' : dueSoon.length > 0 ? 'due_soon' : upcoming.length > 0 ? 'upcoming' : 'none';

    return {
      priority,
      overdue_count: overdue.length,
      due_soon_count: dueSoon.length,
      upcoming_count: upcoming.length,
      overdue,
      due_soon: dueSoon,
      upcoming,
    };
  }

  window.TaskIndicator = window.TaskIndicator || {};
  window.TaskIndicator.helpers = {
    formatDate,
    convertJourneyToSummary,
  };
})();
