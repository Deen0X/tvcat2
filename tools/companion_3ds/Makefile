#---------------------------------------------------------------------------------
.SUFFIXES:
#---------------------------------------------------------------------------------
ifeq ($(strip $(DEVKITARM)),)
$(error "Please set DEVKITARM in your environment. export DEVKITARM=<path>")
endif

include $(DEVKITARM)/base_rules

TARGET		:=	tvcat_companion
BUILD		:=	build
SOURCES		:=	source
INCLUDES	:=	include

ARCH		:=	-march=armv6k -mtune=mpcore -mfloat-abi=hard -mtp=soft

CFLAGS		:=	-g -Wall -O2 -ffunction-sections $(ARCH) \
				$(addprefix -I,$(CURDIR)/$(INCLUDES))
CFLAGS		+=	-DARM11 -D_3DS

LDFLAGS		:=	-specs=3dsx.specs -g $(ARCH) -Wl,-Map,$(notdir $*.map)

LIBS		:=	-lctru -lm
LIBDIRS		:=	$(DEVKITPRO)/libctru/lib

#---------------------------------------------------------------------------------
SOURCES		:=	$(wildcard $(SOURCES)/*.c)
OFILES		:=	$(patsubst %.c,%.o,$(SOURCES))
OFILES		:=	$(addprefix $(BUILD)/,$(notdir $(OFILES)))

#---------------------------------------------------------------------------------
all: $(TARGET).3dsx

$(BUILD):
	@mkdir -p $@

$(BUILD)/%.o: source/%.c | $(BUILD)
	$(CC) -c $< -o $@ $(CFLAGS)

$(TARGET).elf: $(OFILES)
	$(CC) $(LDFLAGS) $^ $(LIBDIRS:%=-L%) $(LIBS) -o $@

$(TARGET).3dsx: $(TARGET).elf
	$(PREFIX)strip $<
	@$(DEVKITARM)/bin/3dsxtool $< $@

clean:
	rm -rf $(BUILD) $(TARGET).elf $(TARGET).3dsx
