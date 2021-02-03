import asyncio
import logging
from pathlib import Path

import discord
import hydra
from discord.ext.commands import (
    Bot,
    CheckFailure,
    CommandError,
    Context,
    has_permissions,
)
from discord.utils import get
from omegaconf import DictConfig

from discord_breakout.breakout import Breakout, create_private_channel, create_role
from discord_breakout.tools.typing import *


@hydra.main(config_path="config", config_name="default.yaml")
def main(cfg: DictConfig):
    intents = discord.Intents.default()
    intents.members = True

    bot = Bot(command_prefix="!", intents=intents)
    logging.basicConfig(level=logging.INFO)

    @has_permissions(administrator=True)
    @bot.command(pass_context=True)
    async def setup(ctx: Context):
        """
        Setup the environment for the bot
        :param ctx:
        :return:
        """
        logging.info("Setting up the bot")

        # TODO customize speaking in lobby
        text_channel = get(ctx.guild.text_channels, name=cfg.lobby_channel)
        if not text_channel:
            text_channel = await ctx.guild.create_text_channel(name=cfg.lobby_channel)

        voice_channel = get(ctx.guild.voice_channels, name=cfg.lobby_channel)
        if not voice_channel:
            voice_channel = await ctx.guild.create_voice_channel(name=cfg.lobby_channel)

        cog_breakout = Breakout(
            bot=bot,
            text_channel=text_channel,
            voice_channel=voice_channel,
            organizer=ctx.message.author,
            verbose=1,
        )
        bot.add_cog(cog_breakout)

    @has_permissions(administrator=True)
    @bot.command(pass_context=True, aliases=["b", "break"])
    async def breakout(
        ctx: Context, seconds_discussion: StrInt = 60, seconds_writing: StrInt = 0
    ):
        """
        Run breakout
        :param ctx:
        :param seconds_discussion:
        :param seconds_writing:
        :return:
        """
        logging.info(f"Registered cogs: {bot.cogs.keys()}")
        if "Breakout" in bot.cogs.keys():
            logging.info(f"{ctx.message.author} invoked command counter")

            await bot.cogs["Breakout"].run(
                ctx=ctx,
                seconds_discussion=int(seconds_discussion),
                seconds_writing=int(seconds_writing),
            )
        else:
            logging.info(f"Please set up the bot first")

    # Technical commands and listeners
    @bot.event
    async def on_ready():
        logging.info(f"We have logged in as {bot.user}")

    @bot.event
    async def on_member_remove(member):
        logging.info(f"{member} has left the server")

    @bot.command()
    async def ping(ctx):
        await ctx.send(f"Your ping is {round(bot.latency * 1000)} ms")

    @bot.command(pass_context=True)
    @has_permissions(administrator=True)
    async def clean(ctx: Context):
        exclude_roles = []
        exclude_members = [ctx.message.author.name]
        coroutines_kick = [
            m.kick() for m in ctx.guild.members if m.display_name not in exclude_members
        ]
        coroutines_delete_role = [
            r.delete() for r in ctx.guild.roles if r.name not in exclude_roles
        ]
        coroutines_delete = [
            c.delete() for c in ctx.guild.channels if not c.name.startswith("__")
        ]
        coroutines_purge = [
            c.purge() for c in ctx.guild.text_channels if c.name.startswith("__")
        ]

        # TODO selective kicking
        await asyncio.gather(
            # *coroutines_kick,
            *coroutines_delete,
            *coroutines_delete_role,
            *coroutines_purge,
        )

    @clean.error
    async def clean_error(error: CommandError, ctx: Context):
        if isinstance(error, CheckFailure):
            logging.info(f"{ctx.message.author} has not rights to clean")

    bot.run(cfg.token, bot=True)


if __name__ == "__main__":
    main()
