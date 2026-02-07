/**
 * Zero Discord Channel Setup Script
 * Creates all categories and channels for the Zero personal assistant
 */

const DISCORD_API = 'https://discord.com/api/v10';

// Channel structure for Zero personal assistant
const CHANNEL_STRUCTURE = [
  {
    category: 'ZERO',
    channels: [
      { name: 'chat', topic: 'Primary conversation channel for general queries with Zero' },
      { name: 'tasks', topic: 'Task tracking, todos, and reminders' },
      { name: 'schedule', topic: 'Calendar items, appointments, and time-based reminders' },
    ]
  },
  {
    category: 'DEVELOPMENT',
    channels: [
      { name: 'code', topic: 'Programming help, code reviews, and debugging' },
      { name: 'projects', topic: 'Project planning and tracking' },
    ]
  },
  {
    category: 'KNOWLEDGE',
    channels: [
      { name: 'research', topic: 'Research queries, learning, and documentation lookups' },
      { name: 'notes', topic: 'Quick notes, ideas, and bookmarks' },
    ]
  },
  {
    category: 'SYSTEM',
    channels: [
      { name: 'notifications', topic: 'Proactive alerts and scheduled reminders from Zero' },
      { name: 'logs', topic: 'Activity history and debugging logs' },
    ]
  }
];

async function discordRequest(endpoint, options = {}) {
  const url = `${DISCORD_API}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      'Authorization': `Bot ${process.env.DISCORD_BOT_TOKEN}`,
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Discord API error: ${response.status} - ${error}`);
  }

  return response.json();
}

async function createCategory(guildId, name) {
  console.log(`Creating category: ${name}`);
  const channel = await discordRequest(`/guilds/${guildId}/channels`, {
    method: 'POST',
    body: JSON.stringify({
      name: name,
      type: 4, // GUILD_CATEGORY
    }),
  });
  console.log(`  Created category "${name}" with ID: ${channel.id}`);
  return channel;
}

async function createTextChannel(guildId, name, topic, parentId) {
  console.log(`  Creating channel: #${name}`);
  const channel = await discordRequest(`/guilds/${guildId}/channels`, {
    method: 'POST',
    body: JSON.stringify({
      name: name,
      type: 0, // GUILD_TEXT
      topic: topic,
      parent_id: parentId,
    }),
  });
  console.log(`    Created #${name} with ID: ${channel.id}`);
  return channel;
}

async function setupChannels() {
  const guildId = process.env.DISCORD_GUILD_ID;
  const botToken = process.env.DISCORD_BOT_TOKEN;

  if (!guildId) {
    console.error('ERROR: DISCORD_GUILD_ID not set in environment');
    process.exit(1);
  }
  if (!botToken) {
    console.error('ERROR: DISCORD_BOT_TOKEN not set in environment');
    process.exit(1);
  }

  console.log('='.repeat(50));
  console.log('Zero Discord Channel Setup');
  console.log('='.repeat(50));
  console.log(`Guild ID: ${guildId}`);
  console.log('');

  const channelIds = {};

  for (const section of CHANNEL_STRUCTURE) {
    // Create category
    const category = await createCategory(guildId, section.category);

    // Small delay to avoid rate limits
    await new Promise(r => setTimeout(r, 500));

    // Create channels under this category
    for (const ch of section.channels) {
      const channel = await createTextChannel(guildId, ch.name, ch.topic, category.id);
      channelIds[ch.name] = channel.id;
      await new Promise(r => setTimeout(r, 500));
    }

    console.log('');
  }

  console.log('='.repeat(50));
  console.log('Setup Complete! Channel IDs:');
  console.log('='.repeat(50));
  console.log(JSON.stringify(channelIds, null, 2));
  console.log('');
  console.log('Add these to your moltbot.json allowChannels:');
  console.log(JSON.stringify(Object.values(channelIds), null, 2));

  return channelIds;
}

// Run the setup
setupChannels().catch(err => {
  console.error('Setup failed:', err.message);
  process.exit(1);
});
