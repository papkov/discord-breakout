import asyncio
import logging

from discord import (
    Guild,
    Invite,
    Member,
    Message,
    PermissionOverwrite,
    Role,
    VoiceChannel,
)
from discord.ext.commands import Bot, Cog, Context
from discord.utils import get

from discord_breakout.tools.typing import *


async def create_role(guild: Guild, name: str) -> Role:
    """
    Creates a new role `name` if it does not exist
    :param guild:
    :param name:
    :return: role
    """
    role = get(guild.roles, name=name)
    if role:
        logging.info(f"Role {name} already exists")
    else:
        logging.info(f"Create role {name}")
        role = await guild.create_role(
            name=name,
            # colour=discord.Colour(0x0062ff),
            mentionable=True,
        )
    return role


async def create_private_channel(
    guild: Guild,
    role: Role,
    user_limit: Optional[int] = None,
    channel_type: Type[Channel] = TextChannel,
    send_and_speak: bool = True,
) -> Channel:
    """
    Creates a private channel of a given type for the role
    :param guild:
    :param role:
    :param user_limit:
    :param channel_type:
    :param send_and_speak:
    :return: channel
    """
    default = guild.default_role
    riddler = get(guild.roles, name="riddler")
    overwrites = {
        riddler: PermissionOverwrite(
            connect=True,
            read_messages=True,
            priority_speaker=True,
            move_members=True,
            manage_roles=True,
        ),
        default: PermissionOverwrite(connect=False, read_messages=False),
        role: PermissionOverwrite(
            connect=True,
            read_messages=True,
            send_messages=send_and_speak,
            speak=send_and_speak,
        ),
    }

    channels = (
        guild.text_channels if channel_type == TextChannel else guild.voice_channels
    )
    channel = get(channels, name=role.name)
    if not channel:
        logging.info(f"Creating {channel_type} {role.name}")
        create_channel = (
            guild.create_text_channel
            if channel_type == TextChannel
            else guild.create_voice_channel
        )
        channel = await create_channel(
            name=role.name, user_limit=user_limit, overwrites=overwrites
        )
    else:
        for role, overwrite in overwrites.items():
            await channel.set_permissions(role, overwrite=overwrite)
    return channel


async def create_role_and_channels(
    ctx: Context,
    guild: Guild,
    channel_name: str,
    user_limit: int,
    bot_id: Optional[int] = None,
) -> Tuple[Role, TextChannel, VoiceChannel]:
    """
    Creates a role and two private channels (voice and text) for a tournament registration
    :param ctx:
    :param guild:
    :param channel_name:
    :param user_limit:
    :param bot_id:
    :return:
    """
    role = await create_role(guild, channel_name)
    member = guild.get_member(ctx.author.id)
    await member.add_roles(role)

    if bot_id is not None:
        bot_member = guild.get_member(bot_id)
        await bot_member.add_roles(role)

    text_channel = await create_private_channel(
        guild, role, user_limit=user_limit, channel_type=TextChannel
    )

    voice_channel = await create_private_channel(
        guild, role, user_limit=user_limit, channel_type=VoiceChannel
    )

    return role, text_channel, voice_channel


class Breakout(Cog):
    """
    Handles moving people between breakout rooms
    """

    def __init__(
        self,
        bot: Bot,
        text_channel: TextChannel,
        voice_channel: VoiceChannel,
        organizer: Member,
        verbose: int = 0,
    ):
        self.bot = bot
        self.text_channel = text_channel
        self.voice_channel = voice_channel
        self.organizer = organizer
        self.room_text_channels = set()
        self.verbose = verbose
        self.waiting = 1

    async def run(
        self, ctx: Context, seconds_discussion: int = 60, seconds_writing: int = 10
    ):
        """
        Run breakout times in two parts with warning
        :param ctx
        :param seconds_discussion: int, breakout time
        :param seconds_writing: int, warning time before moving back to lobby
        :return:
        """
        # check if all the channels exist
        await self.move_players_to_voice(ctx, to_lobby=False)
        await self.countdown_discussion(seconds=seconds_discussion)
        if seconds_writing > 0:
            await self.countdown_writing(seconds=seconds_writing)
        await self.move_players_to_voice(ctx, to_lobby=True)

    @Cog.listener()
    async def on_message(self, message: Message):
        # Ignore messages from the bot
        if message.author == self.bot.user:
            return

        # Broadcast from lobby to breakout rooms
        if message.channel == self.text_channel and not message.content.startswith("!"):
            logging.info("Broadcast message")
            content = ""
            if message.content:
                content += message.content + "\n"
            if message.attachments:
                content += "\n".join([att.url for att in message.attachments])

            await self.send_to_all_channels(message=content)
            return

        # if message.channel not in self.room_text_channels:
        #     logging.info(f"Ignore message from another channel {message.channel}")
        #     return

    async def countdown(self, seconds: int, verbose: bool = False):
        messages = []
        if verbose:
            messages = await self.send_to_all_channels(f"{seconds}")

        for s in reversed(range(seconds)):
            coroutines = [m.edit(content=f"{s}") for m in messages]
            await asyncio.gather(asyncio.sleep(self.waiting), *coroutines)

    async def send_to_all_channels(self, message: str):
        coroutines = [channel.send(message) for channel in self.room_text_channels]
        messages = await asyncio.gather(*coroutines)
        return messages

    async def countdown_discussion(self, seconds: int = 60):
        logging.info(f"Start discussion countdown from {seconds}")
        await asyncio.gather(
            self.send_to_all_channels(f"Breakout started: {seconds} seconds"),
            self.countdown(seconds, verbose=self.verbose > 1),
        )

    async def countdown_writing(self, seconds: int = 10):
        logging.info(f"Start writing countdown from {seconds}")
        await asyncio.gather(
            self.send_to_all_channels(f"{seconds} before the end of breakout"),
            self.countdown(seconds, verbose=self.verbose > 0),
        )
        await self.send_to_all_channels("Время вышло!")

    async def move_players_to_voice(self, ctx: Context, to_lobby: bool = True):
        coroutines = []
        for role in ctx.guild.roles:
            if "@everyone" in role.name or "riddler" in role.name:
                continue
            if to_lobby:
                voice_channel = self.voice_channel
            else:
                # blocking creation of voice channel (returns existing if present)
                voice_channel = await create_private_channel(
                    ctx.guild, role, channel_type=VoiceChannel
                )
                role_text_channel = await create_private_channel(
                    ctx.guild, role, channel_type=TextChannel
                )
                self.room_text_channels.add(role_text_channel)
            for member in role.members:
                coroutines.append(move_member_to_voice(member, voice_channel))
        await asyncio.gather(*coroutines)


async def move_member_to_voice(member: Member, voice_channel: VoiceChannel):
    """
    Helper function to move member to a voice channel with exception handling
    :param member:
    :param voice_channel:
    :return:
    """
    if member.voice and voice_channel != member.voice:
        try:
            await member.move_to(voice_channel)
        except:
            logging.info(
                f"Failed to move member {member.display_name} to channel {voice_channel.name}"
            )
