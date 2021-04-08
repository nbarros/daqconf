import json
import os
import rich.traceback
from rich.console import Console
from os.path import exists, join


CLOCK_SPEED_HZ = 50000000;

# Add -h as default help option
CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

console = Console()


import click

@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-n', '--number-of-data-producers', default=2)
@click.option('-e', '--emulator-mode', is_flag=True)
@click.option('-s', '--data-rate-slowdown-factor', default=1)
@click.option('-r', '--run-number', default=333)
@click.option('-t', '--trigger-rate-hz', default=1.0)
@click.option('-c', '--token-count', default=10)
@click.option('-d', '--data-file', type=click.Path(), default='./frames.bin')
@click.option('-o', '--output-path', type=click.Path(), default='.')
@click.option('--disable-data-storage', is_flag=True)
@click.option('-f', '--use-felix', is_flag=True)
@click.option('--host-df', default='localhost')
@click.option('--host-ru', multiple=True, default=['localhost'])
@click.option('--host-trg', default='localhost')
@click.argument('json_dir', type=click.Path())
def cli(number_of_data_producers, emulator_mode, data_rate_slowdown_factor, run_number, trigger_rate_hz, token_count, data_file, output_path, disable_data_storage, use_felix, host_df, host_ru, host_trg, json_dir):
    """
      JSON_DIR: Json file output folder
    """
    console.log("Loading dataflow config generator")
    from . import dataflow_gen
    console.log("Loading readout config generator")
    from . import readout_gen
    console.log("Loading trg config generator")
    from . import trg_gen
    console.log(f"Generating configs for hosts trg={host_trg} dataflow={host_df} readout={host_ru}")


    if token_count > 0:
        df_token_count = 0
        trigemu_token_count = token_count
    else:
        df_token_count = -1 * token_count
        trigemu_token_count = 0

    network_endpoints={
        "trigdec" : "tcp://{host_trg}:12345",
        "triginh" : "tcp://{host_df}:12346",
    }

    port=12347
    for hostidx in range(len(host_ru)):
        # Should end up something like 'network_endpoints[timesync_0]: "tcp://{host_ru0}:12347"'
        network_endpoints[f"timesync_{hostidx}"] = "tcp://{host_ru" + f"{hostidx}" + "}:" + f"{port}"
        port = port + 1
        network_endpoints[f"frags_{hostidx}"] = "tcp://{host_ru"+ f"{hostidx}" + "}:" + f"{port}"
        port = port + 1
        for idx in range(number_of_data_producers):
            network_endpoints[f"datareq_{hostidx}_{idx}"] = "tcp://{host_df}:"+f"{port}"
            port = port + 1
        hostidx = hostidx + 1


    cmd_data_trg = trg_gen.generate(
        network_endpoints,
        NUMBER_OF_DATA_PRODUCERS = number_of_data_producers,
        DATA_RATE_SLOWDOWN_FACTOR = data_rate_slowdown_factor,
        RUN_NUMBER = run_number, 
        TRIGGER_RATE_HZ = trigger_rate_hz,
        TOKEN_COUNT = trigemu_token_count,
        CLOCK_SPEED_HZ = CLOCK_SPEED_HZ
    )

    console.log("trg cmd data:", cmd_data_trg)

    cmd_data_dataflow = dataflow_gen.generate(
        network_endpoints,
        NUMBER_OF_DATA_PRODUCERS = number_of_data_producers,
        RUN_NUMBER = run_number, 
        OUTPUT_PATH = output_path,
        DISABLE_OUTPUT = disable_data_storage,
        TOKEN_COUNT = df_token_count
    )
    console.log("dataflow cmd data:", cmd_data_dataflow)

    cmd_data_readout = [ readout_gen.generate(
            network_endpoints,
            NUMBER_OF_DATA_PRODUCERS = number_of_data_producers,
            EMULATOR_MODE = emulator_mode,
            DATA_RATE_SLOWDOWN_FACTOR = data_rate_slowdown_factor,
            RUN_NUMBER = run_number, 
            DATA_FILE = data_file,
            FLX_INPUT = use_felix,
            CLOCK_SPEED_HZ = CLOCK_SPEED_HZ,
            HOSTIDX = hostidx
            ) for hostidx in range(len(host_ru))]
    console.log("readout cmd data:", cmd_data_readout)

    if exists(json_dir):
        raise RuntimeError(f"Directory {json_dir} already exists")

    data_dir = join(json_dir, 'data')
    os.makedirs(data_dir)

    app_trgemu="trgemu"
    app_df="dataflow"
    app_ru=[f"ruflx{idx}" if use_felix else f"ruemu{idx}" for idx in range(len(host_ru))]

    jf_trigemu = join(data_dir, app_trgemu)
    jf_df = join(data_dir, app_df)
    jf_ru = [join(data_dir, app_ru[idx]) for idx in range(len(host_ru))]

    cmd_set = ["init", "conf", "start", "stop", "pause", "resume", "scrap"]
    for app,data in [(app_trgemu, cmd_data_trg), (app_df, cmd_data_dataflow)] + list(zip(app_ru, cmd_data_readout)):
        console.log(f"Generating {app} command data json files")
    # for app,data in ((app_trgemu, None), (app_dfru, None)):
        for c in cmd_set:
            with open(f'{join(data_dir, app)}_{c}.json', 'w') as f:
                # f.write(f'{app} {c}')
                json.dump(data[c].pod(), f, indent=4, sort_keys=True)


    console.log(f"Generating top-level command json files")
    start_order = app_ru + [app_df, app_trgemu]
    for c in cmd_set:
        with open(join(json_dir,f'{c}.json'), 'w') as f:
            cfg = {
                "apps": { app: f'data/{app}_{c}' for app in [app_trgemu, app_df] + app_ru }
            }
            if c == 'start':
                cfg['order'] = start_order
            elif c == 'stop':
                cfg['order'] = start_order[::-1]
            elif c in ('resume', 'pause'):
                del cfg['apps'][app_df]
                for ruapp in app_ru:
                    del cfg['apps'][ruapp]

            json.dump(cfg, f, indent=4, sort_keys=True)


    console.log(f"Generating boot json file")
    with open(join(json_dir,'boot.json'), 'w') as f:
        cfg = {
            "env" : {
                "DBT_ROOT": "env",
                "DBT_AREA_ROOT": "env"
            },
            "hosts": {
                "host_df": host_df,
                "host_trg": host_trg
            },
            "apps" : {
                app_trgemu : {
                    "exec": "daq_application",
                    "host": "host_trg",
                    "port": 3333
                },
                app_df: {
                    "exec": "daq_application",
                    "host": "host_df",
                    "port": 3334
                }
            }
        }
        appport=3335
        for hostidx in range(len(host_ru)):
            cfg["hosts"][f"host_ru{hostidx}"] = host_ru[hostidx]
            cfg["apps"][app_ru[hostidx]] = {
                    "exec": "daq_application",
                    "host": f"host_ru{hostidx}",
                    "port": appport }
            appport = appport + 1
        json.dump(cfg, f, indent=4, sort_keys=True)
    console.log(f"MDAapp config generated in {json_dir}")


if __name__ == '__main__':

    try:
        cli(show_default=True, standalone_mode=True)
    except Exception as e:
        console.print_exception()
