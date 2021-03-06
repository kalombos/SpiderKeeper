import time
from SpiderKeeper.app.proxy import agent
from SpiderKeeper.app.blueprints.dashboard.model import Project, JobInstance, SpiderInstance
from twisted.logger import Logger


logger = Logger()


class JobsAdder(object):
    def __init__(self, scheduler, flask_app):
        self.scheduler = scheduler
        self.flask_app = flask_app

    def with_app_context(self, f):
        def f_with_context(*args, **kwargs):
            with self.flask_app.app_context():
                f(*args, **kwargs)

        return f_with_context

    def sync_projects(self):
        """
        sync projects
        :return:
        """
        agent.get_project_list()
        logger.debug('[sync_projects]')

    def sync_job_execution_status_job(self):
        """
        sync job execution running status
        :return:
        """
        for project in Project.query.all():
            agent.sync_job_status(project)
        logger.debug('[sync_job_execution_status]')

    def sync_spiders(self):
        """
        sync spiders
        :return:
        """
        for project in Project.query.all():
            spider_instance_list = agent.get_spider_list(project)
            SpiderInstance.update_spider_instances(project.id, spider_instance_list)
        logger.debug('[sync_spiders]')

    def run_spider_job(self, job_instance_id):
        """
        run spider by scheduler
        :param job_instance_id:
        :return:
        """
        try:
            job_instance = JobInstance.query.get(job_instance_id)
            agent.start_spider(job_instance)
            logger.info('[run_spider_job][project:%s][spider_name:%s][job_instance_id:%s]' % (
                job_instance.project_id, job_instance.spider_name, job_instance.id))
        except Exception as e:
            logger.error('[run_spider_job] ' + str(e))

    def reload_runnable_spider_job_execution(self):
        """
        add periodic job to scheduler
        :return:
        """
        running_job_ids = set([job.id for job in self.scheduler.get_jobs()])
        logger.debug('[running_job_ids] %s' % ','.join(running_job_ids))
        available_job_ids = set()
        # add new job to schedule
        for job_instance in JobInstance.query.filter_by(enabled=0, run_type="periodic").all():
            job_id = "spider_job_%s:%s" % (
                job_instance.id, int(time.mktime(job_instance.date_modified.timetuple()))
            )
            available_job_ids.add(job_id)
            if job_id not in running_job_ids:
                self.add_job(
                    self.run_spider_job,
                    args=(job_instance.id,),
                    trigger='cron',
                    id=job_id,
                    minute=job_instance.cron_minutes,
                    hour=job_instance.cron_hour,
                    day=job_instance.cron_day_of_month,
                    day_of_week=job_instance.cron_day_of_week,
                    month=job_instance.cron_month,
                    second=0,
                    max_instances=999,
                    misfire_grace_time=60 * 60,
                    coalesce=True)
                logger.info(
                    '[load_spider_job][project:%s][spider_name:%s][job_instance_id:%s][job_id:%s]'
                    % (job_instance.project_id, job_instance.spider_name, job_instance.id, job_id)
                )
        # remove invalid jobs
        for invalid_job_id in filter(lambda job_id: job_id.startswith("spider_job_"),
                                     running_job_ids.difference(available_job_ids)):
            self.scheduler.remove_job(invalid_job_id)
            logger.info('[drop_spider_job][job_id:%s]' % invalid_job_id)

    def add_job(self, job, *args, **kwargs):
        self.scheduler.add_job(self.with_app_context(job), *args, **kwargs)

    def add_jobs(self):
        self.add_job(self.sync_projects, 'interval', seconds=10, id='sys_sync_projects')
        self.add_job(
            self.sync_job_execution_status_job, 'interval', seconds=5, id='sys_sync_status'
        )
        self.add_job(self.sync_spiders, 'interval', seconds=10, id='sys_sync_spiders')
        self.add_job(
            self.reload_runnable_spider_job_execution, 'interval',
            seconds=30, id='sys_reload_job'
        )
